"""API-key management for the dashboard + JSON API.

Creating a key returns the raw value exactly once (stored hashed thereafter),
matching the flow the CLI's README describes.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.auth.api_keys import create_api_key_async
from synapse_backend.api.deps import get_current_user
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import ApiKey, User

router = APIRouter(tags=["api-keys"])


@router.get("/api/keys")
async def list_keys(
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    rows = (
        await session.execute(select(ApiKey).where(ApiKey.user_id == user.id))
    ).scalars().all()
    return {
        "keys": [
            {
                "id": k.id,
                "name": k.name,
                "prefix": k.key_prefix,
                "active": k.active,
                "servers_generated": k.servers_generated,
                "max_mcp_servers": k.max_mcp_servers,
                "lines_indexed": k.lines_indexed,
                "max_lines_indexed": k.max_lines_indexed,
            }
            for k in rows
        ]
    }


@router.post("/api/keys")
async def create_key_json(
    name: str = Form(default="default"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    api_key, raw = await create_api_key_async(session, user.id, name=name)
    return {"id": api_key.id, "name": api_key.name, "key": raw}


@router.post("/keys/create")
async def create_key_form(
    name: str = Form(default="default"),
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    """Dashboard form action — mint a key and show it once via query param."""
    _, raw = await create_api_key_async(session, user.id, name=name)
    return RedirectResponse(
        url=f"/app?new_key={raw}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.post("/keys/{key_id}/revoke")
async def revoke_key(
    key_id: str,
    user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_async_session),
) -> RedirectResponse:
    key = await session.get(ApiKey, key_id)
    if key is not None and key.user_id == user.id:
        key.active = False
        await session.commit()
    return RedirectResponse(url="/app", status_code=status.HTTP_303_SEE_OTHER)
