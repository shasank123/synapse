"""CLI telemetry endpoint — ``POST /telemetry/cli``.

The CLI fire-and-forgets events here (Authorization: Bearer <api_key>). Analyze
events carry a delta of newly-indexed lines which we add to the key's quota.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from synapse_backend.api.deps import get_api_key_from_bearer
from synapse_backend.db.database import get_async_session
from synapse_backend.db.models import ApiKey, Event

router = APIRouter(tags=["telemetry"])


class TelemetryPayload(BaseModel):
    event_type: str
    working_dir_hash: str = ""
    lines_count: int = 0
    tool_count: int = 0
    candidate_count: int = 0
    duration_ms: int = 0


@router.post("/telemetry/cli")
async def telemetry_cli(
    payload: TelemetryPayload,
    api_key: ApiKey = Depends(get_api_key_from_bearer),
    session: AsyncSession = Depends(get_async_session),
) -> dict:
    session.add(
        Event(
            api_key_id=api_key.id,
            event_type=payload.event_type,
            working_dir_hash=payload.working_dir_hash,
            lines_count=payload.lines_count,
            tool_count=payload.tool_count,
            candidate_count=payload.candidate_count,
            duration_ms=payload.duration_ms,
        )
    )
    # Analyze reports a delta of newly indexed lines → add to quota usage.
    if payload.event_type == "analyze" and payload.lines_count:
        api_key.lines_indexed = (api_key.lines_indexed or 0) + payload.lines_count
    api_key.last_used_at = dt.datetime.now(dt.timezone.utc)
    await session.commit()
    return {"ok": True}
