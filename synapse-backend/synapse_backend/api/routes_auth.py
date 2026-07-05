"""Dashboard auth: register / login / logout (cookie-based JWT session)."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.auth.passwords import (
    create_access_token,
    hash_password,
    verify_password,
)
from synapse_backend.config import settings
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import User

router = APIRouter(tags=["auth"])


def _set_session_cookie(response: Response, user: User) -> None:
    token = create_access_token(user.id, user.email)
    response.set_cookie(
        "synapse_session",
        token,
        max_age=settings.jwt_ttl_seconds,
        httponly=True,
        samesite="lax",
    )


@router.post("/register")
async def register(
    email: str = Form(...),
    password: str = Form(...),
    full_name: str = Form(default=""),
    session: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    existing = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        return RedirectResponse(
            url="/register?error=" + quote("Email already registered"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
    user = User(
        email=email, password_hash=hash_password(password), full_name=full_name
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)

    response = RedirectResponse(url="/app", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user)
    return response


@router.post("/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    session: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    user = (
        await session.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        return RedirectResponse(
            url="/login?error=" + quote("Invalid email or password"),
            status_code=status.HTTP_303_SEE_OTHER,
        )

    response = RedirectResponse(url="/app", status_code=status.HTTP_303_SEE_OTHER)
    _set_session_cookie(response, user)
    return response


@router.get("/logout")
async def logout() -> RedirectResponse:
    response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("synapse_session")
    return response
