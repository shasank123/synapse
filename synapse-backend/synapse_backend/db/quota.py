"""Quota snapshots and usage accounting.

The CLI asks two quota questions via TrackEvent:
  * ``quota_check`` -> just needs (exceeded, message)
  * ``quota_info``  -> needs the full snapshot for `synapse info`

Both are answered from a single ``api_keys`` row keyed by ``sha256(api_key)``.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy.orm import Session

from synapse_backend.auth.api_keys import get_by_hash_sync
from synapse_backend.db.models import ApiKey, Event, MCPServer


def empty_snapshot() -> dict:
    """Snapshot for an unknown/invalid key — fail open, nothing exceeded."""
    return {
        "mcp_servers_count": 0,
        "max_mcp_servers": 0,
        "lines_indexed": 0,
        "max_lines_indexed": 0,
        "quota_exceeded": False,
        "quota_message": "",
    }


def snapshot_from_key(api_key: ApiKey) -> dict:
    return {
        "mcp_servers_count": api_key.servers_generated,
        "max_mcp_servers": api_key.max_mcp_servers,
        "lines_indexed": api_key.lines_indexed,
        "max_lines_indexed": api_key.max_lines_indexed,
        "quota_exceeded": api_key.quota_exceeded,
        "quota_message": api_key.quota_message(),
    }


def snapshot_by_hash(session: Session, key_hash: str) -> dict:
    api_key = get_by_hash_sync(session, key_hash)
    if api_key is None:
        return empty_snapshot()
    return snapshot_from_key(api_key)


def touch_last_used(session: Session, api_key: ApiKey) -> None:
    api_key.last_used_at = dt.datetime.now(dt.timezone.utc)
    session.commit()


def record_lines_indexed(session: Session, api_key: ApiKey, delta: int) -> None:
    """Add newly indexed lines to the running total (delta already computed by CLI)."""
    if delta <= 0:
        return
    api_key.lines_indexed = (api_key.lines_indexed or 0) + delta
    session.commit()


def record_server_generated(
    session: Session,
    api_key: ApiKey,
    *,
    name: str,
    query: str,
    tool_count: int,
    resource_count: int,
    line_count: int,
    storage_uri: str = "",
    working_dir_hash: str = "",
) -> MCPServer:
    """Increment the server counter and persist an MCPServer record."""
    api_key.servers_generated = (api_key.servers_generated or 0) + 1
    server = MCPServer(
        api_key_id=api_key.id,
        name=name,
        query=query[:4000],
        tool_count=tool_count,
        resource_count=resource_count,
        line_count=line_count,
        storage_uri=storage_uri,
        working_dir_hash=working_dir_hash,
    )
    session.add(server)
    session.commit()
    session.refresh(server)
    return server


def log_event(
    session: Session,
    *,
    api_key: ApiKey | None,
    event_type: str,
    working_dir_hash: str = "",
    lines_count: int = 0,
    tool_count: int = 0,
    candidate_count: int = 0,
    duration_ms: int = 0,
    confidence: float = 0.0,
) -> None:
    session.add(
        Event(
            api_key_id=api_key.id if api_key else None,
            event_type=event_type,
            working_dir_hash=working_dir_hash,
            lines_count=lines_count,
            tool_count=tool_count,
            candidate_count=candidate_count,
            duration_ms=duration_ms,
            confidence=confidence,
        )
    )
    session.commit()
