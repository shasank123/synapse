"""FastAPI dependencies: current user (JWT cookie) and Bearer API-key auth."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.auth.api_keys import validate_raw_key_async
from synapse_backend.auth.passwords import decode_access_token
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import ApiKey, User


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
) -> User:
    """Resolve the dashboard user from the ``synapse_session`` JWT cookie."""
    token = request.cookies.get("synapse_session", "")
    payload = decode_access_token(token) if token else None
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    user = await session.get(User, payload.get("sub"))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user"
        )
    return user


async def get_api_key_from_bearer(
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_async_session),
) -> ApiKey:
    """Resolve the API key from an ``Authorization: Bearer <key>`` header.

    Used by the CLI telemetry endpoint.
    """
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token"
        )
    raw_key = authorization.split(" ", 1)[1].strip()
    api_key = await validate_raw_key_async(session, raw_key)
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired API key",
        )
    return api_key
