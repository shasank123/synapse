"""API-key generation, hashing and lookup.

Key format: ``syn-api-<43-char-urlsafe-token>``.

We never store the raw key — only ``key_prefix`` (for display, e.g. ``syn-api-AbC12``)
and ``key_hash = sha256(raw_key)``. This mirrors what the CLI does: it sends the
raw key as ``x-api-key`` gRPC metadata (Build/Detect) and ``sha256(key)`` as the
``api_key_hash`` field on TrackEvent — so both auth paths resolve to ``key_hash``.
"""

from __future__ import annotations

import hashlib
import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from synapse_backend.db.models import ApiKey

KEY_PREFIX = "syn-api-"
PREFIX_DISPLAY_LEN = 13  # "syn-api-" + 5 chars


def hash_key(raw_key: str) -> str:
    """sha256 hex digest of a raw key — the value stored and looked up."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_raw_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def new_key_material() -> tuple[str, str, str]:
    """Return (raw_key, key_prefix, key_hash) for a freshly minted key."""
    raw = generate_raw_key()
    return raw, raw[:PREFIX_DISPLAY_LEN], hash_key(raw)


# ── Sync lookups (gRPC / Celery) ─────────────────────────────────────────────
def get_by_hash_sync(session: Session, key_hash: str) -> ApiKey | None:
    if not key_hash:
        return None
    return session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
    ).scalar_one_or_none()


def validate_raw_key_sync(session: Session, raw_key: str) -> ApiKey | None:
    """Resolve a raw ``x-api-key`` to its ApiKey row, or None if invalid."""
    if not raw_key:
        return None
    return get_by_hash_sync(session, hash_key(raw_key))


# ── Async lookups (FastAPI) ──────────────────────────────────────────────────
async def get_by_hash_async(session: AsyncSession, key_hash: str) -> ApiKey | None:
    if not key_hash:
        return None
    result = await session.execute(
        select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.active.is_(True))
    )
    return result.scalar_one_or_none()


async def validate_raw_key_async(session: AsyncSession, raw_key: str) -> ApiKey | None:
    if not raw_key:
        return None
    return await get_by_hash_async(session, hash_key(raw_key))


def create_api_key_sync(
    session: Session, user_id: str, name: str = "default"
) -> tuple[ApiKey, str]:
    """Create and persist a new key. Returns (row, raw_key) — raw shown once."""
    raw, prefix, key_hash = new_key_material()
    api_key = ApiKey(user_id=user_id, key_prefix=prefix, key_hash=key_hash, name=name)
    session.add(api_key)
    session.commit()
    session.refresh(api_key)
    return api_key, raw


async def create_api_key_async(
    session: AsyncSession, user_id: str, name: str = "default"
) -> tuple[ApiKey, str]:
    raw, prefix, key_hash = new_key_material()
    api_key = ApiKey(user_id=user_id, key_prefix=prefix, key_hash=key_hash, name=name)
    session.add(api_key)
    await session.commit()
    await session.refresh(api_key)
    return api_key, raw
