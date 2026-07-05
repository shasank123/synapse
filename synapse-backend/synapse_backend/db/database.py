"""SQLAlchemy engines and session factories.

Two flavours are provided because the platform is split across sync and async
runtimes:

* **async** (``AsyncSessionLocal``) — used by the FastAPI REST API.
* **sync** (``SessionLocal``) — used by the gRPC servicer and Celery worker,
  which run their own event loops / threads and are simpler with sync DB access.

Both point at the same Postgres database; only the driver differs.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from synapse_backend.config import settings


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


# ── Async (FastAPI) ──────────────────────────────────────────────────────────
async_engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)
AsyncSessionLocal = async_sessionmaker(
    async_engine, class_=AsyncSession, expire_on_commit=False
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async session."""
    async with AsyncSessionLocal() as session:
        yield session


# ── Sync (gRPC / Celery) ─────────────────────────────────────────────────────
sync_engine = create_engine(
    settings.database_url_sync,
    echo=False,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(bind=sync_engine, class_=Session, expire_on_commit=False)


def get_sync_session() -> Generator[Session, None, None]:
    """Context-manager style helper for sync code paths."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
