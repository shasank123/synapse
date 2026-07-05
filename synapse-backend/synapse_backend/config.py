"""Central configuration, loaded from environment variables.

Every service (gRPC, API, worker) imports ``settings`` from here so the whole
platform is configured from one ``.env`` file. See ``.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_name: str = "synapse-backend"
    environment: str = Field(default="development")
    log_level: str = Field(default="INFO")

    # ── gRPC server ──────────────────────────────────────────────────────────
    grpc_host: str = Field(default="0.0.0.0")
    grpc_port: int = Field(default=50051)
    grpc_max_message_mb: int = Field(default=100)

    # ── REST API ─────────────────────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    # Secret used to sign dashboard session JWTs.
    jwt_secret: str = Field(default="dev-insecure-change-me")
    jwt_ttl_seconds: int = Field(default=86400)

    # ── Postgres ─────────────────────────────────────────────────────────────
    # Async URL (asyncpg) for the API; sync URL (psycopg) for gRPC/worker.
    database_url: str = Field(
        default="postgresql+asyncpg://synapse:synapse@localhost:5432/synapse"
    )
    database_url_sync: str = Field(
        default="postgresql+psycopg://synapse:synapse@localhost:5432/synapse"
    )

    # ── Redis (Celery broker + cache) ────────────────────────────────────────
    redis_url: str = Field(default="redis://localhost:6379/0")

    # ── Qdrant (vector DB) ───────────────────────────────────────────────────
    qdrant_url: str = Field(default="http://localhost:6333")
    qdrant_collection: str = Field(default="synapse_functions")
    embedding_dim: int = Field(default=384)

    # ── Object storage (MinIO / S3) for generated MCP servers ────────────────
    s3_endpoint_url: str = Field(default="http://localhost:9000")
    s3_access_key: str = Field(default="minioadmin")
    s3_secret_key: str = Field(default="minioadmin")
    s3_bucket: str = Field(default="synapse-mcp-servers")
    s3_region: str = Field(default="us-east-1")

    # ── LLM provider ─────────────────────────────────────────────────────────
    # "mock" runs the full pipeline with no external key (default for the POC).
    llm_provider: str = Field(default="mock")  # mock | anthropic | openai
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")
    anthropic_model: str = Field(default="claude-sonnet-5")
    openai_model: str = Field(default="gpt-4o")
    llm_max_tokens: int = Field(default=4096)
    llm_temperature: float = Field(default=0.1)

    # ── Quota (per API key) ──────────────────────────────────────────────────
    default_max_mcp_servers: int = Field(default=25)
    default_max_lines_indexed: int = Field(default=1_000_000)

    @property
    def grpc_max_message_bytes(self) -> int:
        return self.grpc_max_message_mb * 1024 * 1024

    @property
    def cors_origins(self) -> List[str]:
        return ["*"] if self.environment == "development" else []


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
