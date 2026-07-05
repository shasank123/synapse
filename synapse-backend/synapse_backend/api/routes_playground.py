"""In-browser Playground: paste code → detect tools → generate an MCP server.

Runs the SAME pipeline the gRPC Build uses, but in-process in the API so the
whole thing works from the browser with no CLI. Attributes the generated server
to the logged-in user's first active API key (so quota + the dashboard update).
"""

from __future__ import annotations

import ast
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from synapse_backend.auth.api_keys import create_api_key_sync
from synapse_backend.auth.passwords import decode_access_token
from synapse_backend.db import quota as quota_svc
from synapse_backend.db.database import SessionLocal
from synapse_backend.db.models import ApiKey, User

logger = logging.getLogger(__name__)
router = APIRouter(tags=["playground"])

import os  # noqa: E402

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)

SAMPLE_CODE = '''def get_supplier_risk(supplier_id: str, fiscal_year: int, region: str = "") -> dict:
    """Calculate a comprehensive risk score for a supplier."""
    ...

def search_parts(query: str, region: str = "", max_results: int = 10) -> list:
    """Search for parts across suppliers matching a text query."""
    ...

def create_purchase_order(supplier_id: str, part_number: str, quantity: int) -> dict:
    """Create a purchase order for a part from a supplier."""
    ...

def _normalize_score(raw: float) -> float:
    """Private helper — should be filtered out."""
    ...
'''


def _user_from_cookie(request: Request, session) -> User | None:
    token = request.cookies.get("synapse_session", "")
    payload = decode_access_token(token) if token else None
    if not payload:
        return None
    return session.get(User, payload.get("sub"))


def _extract_functions(code: str) -> list[dict]:
    tree = ast.parse(code)  # raises SyntaxError -> handled by caller
    funcs: list[dict] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        params = [a.arg for a in node.args.args]
        arg_src = ", ".join(ast.unparse(a) for a in node.args.args)
        ret = ast.unparse(node.returns) if node.returns else ""
        sig = f"def {node.name}({arg_src})" + (f" -> {ret}" if ret else "")
        funcs.append(
            {
                "name": node.name,
                "file_path": "pasted_module.py",
                "signature": sig,
                "docstring": ast.get_docstring(node) or "",
                "return_type": ret,
                "param_names": params,
                "line_number": node.lineno,
                "is_async": isinstance(node, ast.AsyncFunctionDef),
            }
        )
    return funcs


@router.get("/app/playground", response_class=HTMLResponse)
async def playground_page(request: Request):
    # Auth check (sync session is fine here).
    session = SessionLocal()
    try:
        user = _user_from_cookie(request, session)
    finally:
        session.close()
    if user is None:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(
        request, "playground.html", {"user": user, "sample_code": SAMPLE_CODE}
    )


@router.post("/api/playground/build")
def playground_build(request: Request, code: str = Form(...)) -> JSONResponse:
    """Synchronous (threadpool) endpoint: run detect + build in-process."""
    from synapse_backend.agents.detector import detect
    from synapse_backend.agents.pipeline import run_build

    session = SessionLocal()
    try:
        user = _user_from_cookie(request, session)
        if user is None:
            return JSONResponse({"error": "Not authenticated"}, status_code=401)

        try:
            functions = _extract_functions(code)
        except SyntaxError as exc:
            return JSONResponse(
                {"error": f"Python syntax error: {exc.msg} (line {exc.lineno})"},
                status_code=400,
            )
        if not functions:
            return JSONResponse(
                {"error": "No top-level functions found in the pasted code."},
                status_code=400,
            )

        candidates = detect(functions, "playground project")
        if not candidates:
            return JSONResponse(
                {"error": "No functions qualified as MCP tool candidates."},
                status_code=400,
            )

        stages: list[dict] = []

        def emit(stage, message, progress, agent_name="", task_name=""):
            stages.append(
                {"stage": stage, "message": message, "progress": progress,
                 "agent": agent_name}
            )

        result = run_build(
            query="Playground: expose the detected functions as MCP tools",
            project_schema="playground project",
            working_dir="playground",
            output_file="mcp_server.py",
            context_bundle={"functions": candidates},
            emit=emit,
        )

        # Attribute to the user's first active key (create one if none).
        api_key = session.execute(
            select(ApiKey).where(ApiKey.user_id == user.id, ApiKey.active.is_(True))
        ).scalars().first()
        if api_key is None:
            api_key, _ = create_api_key_sync(session, user.id, name="playground")

        if result.get("success"):
            _finalize(session, api_key, result)

        return JSONResponse(
            {
                "success": result.get("success", False),
                "tool_count": result.get("tool_count", 0),
                "server_code": result.get("server_code", ""),
                "documentation": result.get("documentation", ""),
                "stages": stages,
                "candidates": [
                    {"name": c["name"], "subcategory": c.get("subcategory", ""),
                     "confidence": round(float(c.get("confidence", 0)), 2)}
                    for c in candidates
                ],
                "extracted": len(functions),
                "error": result.get("error", ""),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("playground build failed")
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        session.close()


def _finalize(session, api_key, result: dict) -> None:
    try:
        from synapse_backend.storage.s3 import put_server_code

        server = quota_svc.record_server_generated(
            session,
            api_key,
            name="playground_mcp_server.py",
            query="playground",
            tool_count=int(result.get("tool_count", 0)),
            resource_count=0,
            line_count=len((result.get("server_code") or "").splitlines()),
        )
        uri = put_server_code(api_key.id, server.id, result.get("server_code", ""))
        if uri:
            server.storage_uri = uri
            session.commit()
        quota_svc.log_event(
            session, api_key=api_key, event_type="playground_build",
            tool_count=int(result.get("tool_count", 0)),
        )
    except Exception:  # noqa: BLE001
        logger.exception("playground finalize failed")
