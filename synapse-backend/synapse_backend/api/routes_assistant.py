"""Assistant (chat) — the end-user experience: ask in NL, get answers.

GET  /app/assistant       chat page (auth required)
POST /api/assistant/chat  {message} -> {answer, tool, args, result, trace}
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from synapse_backend.auth.passwords import decode_access_token
from synapse_backend.db.database import SessionLocal
from synapse_backend.db.models import User
from synapse_backend.demo import agent
from synapse_backend.demo.tools import TOOLS

router = APIRouter(tags=["assistant"])

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


def _user(request: Request) -> User | None:
    token = request.cookies.get("synapse_session", "")
    payload = decode_access_token(token) if token else None
    if not payload:
        return None
    session = SessionLocal()
    try:
        return session.get(User, payload.get("sub"))
    finally:
        session.close()


@router.get("/app/assistant", response_class=HTMLResponse)
async def assistant_page(request: Request):
    user = _user(request)
    if user is None:
        return RedirectResponse(url="/login")
    tools = [{"name": t.name, "description": t.description} for t in TOOLS]
    return templates.TemplateResponse(
        request, "assistant.html", {"user": user, "tools": tools}
    )


@router.post("/api/assistant/chat")
def assistant_chat(request: Request, message: str = Form(...)) -> JSONResponse:
    if _user(request) is None:
        return JSONResponse({"error": "Not authenticated"}, status_code=401)
    return JSONResponse(agent.answer(message))
