"""ORM models — the metadata layer described in the understanding doc.

Tables:
  * users          — dashboard accounts (email/password).
  * api_keys       — one or more keys per user; the CLI authenticates with these.
  * mcp_servers    — record of each MCP server generated via `synapse build`.
  * events         — CLI telemetry (init/analyze/build/detect) for quota + analytics.

Quota is tracked directly on ``api_keys`` (servers_generated, lines_indexed)
so a single row read answers the CLI's quota queries.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from synapse_backend.config import settings
from synapse_backend.db.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    api_keys: Mapped[list["ApiKey"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    # We store only prefix + sha256(key). The raw key is shown to the user once.
    key_prefix: Mapped[str] = mapped_column(String(16), index=True)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), default="default")
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    # Quota counters + limits.
    servers_generated: Mapped[int] = mapped_column(Integer, default=0)
    lines_indexed: Mapped[int] = mapped_column(BigInteger, default=0)
    max_mcp_servers: Mapped[int] = mapped_column(
        Integer, default=settings.default_max_mcp_servers
    )
    max_lines_indexed: Mapped[int] = mapped_column(
        BigInteger, default=settings.default_max_lines_indexed
    )

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_used_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship(back_populates="api_keys")
    mcp_servers: Mapped[list["MCPServer"]] = relationship(
        back_populates="api_key", cascade="all, delete-orphan"
    )

    # ── quota helpers ────────────────────────────────────────────────────────
    @property
    def servers_exceeded(self) -> bool:
        return self.servers_generated >= self.max_mcp_servers

    @property
    def lines_exceeded(self) -> bool:
        return self.lines_indexed >= self.max_lines_indexed

    @property
    def quota_exceeded(self) -> bool:
        return self.servers_exceeded or self.lines_exceeded

    def quota_message(self) -> str:
        if self.servers_exceeded:
            return (
                f"❌ MCP server quota reached "
                f"({self.servers_generated}/{self.max_mcp_servers}). "
                f"Delete a server or upgrade your plan."
            )
        if self.lines_exceeded:
            return (
                f"❌ Lines-indexed quota reached "
                f"({self.lines_indexed:,}/{self.max_lines_indexed:,}). "
                f"Upgrade your plan to index more code."
            )
        return ""


class MCPServer(Base):
    __tablename__ = "mcp_servers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    api_key_id: Mapped[str] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), index=True
    )

    name: Mapped[str] = mapped_column(String(255), default="mcp_server")
    query: Mapped[str] = mapped_column(Text, default="")
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    resource_count: Mapped[int] = mapped_column(Integer, default=0)
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    # Where the generated source is stored in S3/MinIO (s3://bucket/key).
    storage_uri: Mapped[str] = mapped_column(String(512), default="")
    working_dir_hash: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    api_key: Mapped["ApiKey"] = relationship(back_populates="mcp_servers")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    api_key_id: Mapped[str | None] = mapped_column(
        ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(50), index=True)
    working_dir_hash: Mapped[str] = mapped_column(String(64), default="")
    lines_count: Mapped[int] = mapped_column(BigInteger, default=0)
    tool_count: Mapped[int] = mapped_column(Integer, default=0)
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
