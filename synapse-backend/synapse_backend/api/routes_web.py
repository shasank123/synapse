"""Web pages: public marketing site + authed dashboard (Jinja2)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.auth.passwords import decode_access_token
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import ApiKey, Lead, MCPServer, User

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


async def _optional_user(request: Request, session: AsyncSession) -> User | None:
    token = request.cookies.get("synapse_session", "")
    payload = decode_access_token(token) if token else None
    if not payload:
        return None
    return await session.get(User, payload.get("sub"))


# ── public marketing site ────────────────────────────────────────────────────
@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    demo_sent: int = 0,
    session: AsyncSession = Depends(get_async_session),
):
    user = await _optional_user(request, session)
    return templates.TemplateResponse(
        request, "landing.html", {"user": user, "demo_sent": bool(demo_sent)}
    )


@router.get("/pricing", response_class=HTMLResponse)
async def pricing(request: Request, session: AsyncSession = Depends(get_async_session)):
    return templates.TemplateResponse(
        request, "pricing.html", {"user": await _optional_user(request, session)}
    )


@router.get("/usecases", response_class=HTMLResponse)
async def usecases(request: Request, session: AsyncSession = Depends(get_async_session)):
    return templates.TemplateResponse(
        request, "usecases.html", {"user": await _optional_user(request, session)}
    )


@router.get("/docs", response_class=HTMLResponse)
async def docs(request: Request, session: AsyncSession = Depends(get_async_session)):
    return templates.TemplateResponse(
        request, "docs.html", {"user": await _optional_user(request, session)}
    )


_LEGAL = {
    "privacy": (
        "Privacy Policy",
        [
            "Synapse processes only the code context you explicitly analyze. Source code is "
            "parsed locally by the CLI; the backend receives function metadata and the context "
            "you select for a build.",
            "API keys are stored hashed (SHA-256). Passwords are stored using PBKDF2. Generated "
            "MCP server code is stored encrypted at rest in object storage.",
            "We collect minimal telemetry (event type, hashed working directory, counts) to "
            "enforce quotas and improve the product. We never sell your data.",
        ],
    ),
    "terms": (
        "Terms & Conditions",
        [
            "Synapse is provided by 2nd Brain Labs. By using the platform you agree to use it "
            "only on codebases you are authorized to access.",
            "The service is provided on an as-is basis during Early Access. Generated code should "
            "be reviewed before production use.",
            "Quotas apply per plan. Abuse, reverse engineering of other tenants' data, or attempts "
            "to exceed authorized access are prohibited.",
        ],
    ),
}


@router.get("/legal/{doc}", response_class=HTMLResponse)
async def legal(
    doc: str, request: Request, session: AsyncSession = Depends(get_async_session)
):
    heading, paragraphs = _LEGAL.get(doc, ("Legal", ["Document not found."]))
    return templates.TemplateResponse(
        request,
        "legal.html",
        {
            "user": await _optional_user(request, session),
            "heading": heading,
            "paragraphs": paragraphs,
        },
    )


@router.post("/demo")
async def demo(
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    company: str = Form(default=""),
    phone: str = Form(default=""),
    message: str = Form(default=""),
    session: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    session.add(
        Lead(
            first_name=first_name,
            last_name=last_name,
            email=email,
            company=company,
            phone=phone,
            message=message,
        )
    )
    await session.commit()
    return RedirectResponse(url="/?demo_sent=1#demo", status_code=303)


# ── auth pages ───────────────────────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, error: str = ""):
    return templates.TemplateResponse(request, "register.html", {"error": error})


# ── dashboard (auth required) ────────────────────────────────────────────────
@router.get("/app", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    new_key: str = "",
    session: AsyncSession = Depends(get_async_session),
):
    user = await _optional_user(request, session)
    if user is None:
        return RedirectResponse(url="/login")

    keys = (
        await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    ).scalars().all()
    key_ids = [k.id for k in keys]
    servers = []
    if key_ids:
        servers = (
            await session.execute(
                select(MCPServer)
                .where(MCPServer.api_key_id.in_(key_ids))
                .order_by(MCPServer.created_at.desc())
                .limit(20)
            )
        ).scalars().all()

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"user": user, "keys": keys, "servers": servers, "new_key": new_key},
    )
