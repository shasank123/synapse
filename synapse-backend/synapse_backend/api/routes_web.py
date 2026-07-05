"""Web dashboard pages (Jinja2)."""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.auth.passwords import decode_access_token
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import ApiKey, MCPServer, User

router = APIRouter(tags=["web"])

_TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "templates")
templates = Jinja2Templates(directory=_TEMPLATES_DIR)


async def _optional_user(request: Request, session: AsyncSession) -> User | None:
    token = request.cookies.get("synapse_session", "")
    payload = decode_access_token(token) if token else None
    if not payload:
        return None
    return await session.get(User, payload.get("sub"))


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {})


@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse(request, "register.html", {})


@router.get("/", response_class=HTMLResponse)
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
        {
            "user": user,
            "keys": keys,
            "servers": servers,
            "new_key": new_key,
        },
    )
