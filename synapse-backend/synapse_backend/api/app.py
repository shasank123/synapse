"""FastAPI application: REST API + web dashboard.

Mounted routers:
  * /telemetry/cli        — CLI telemetry (Bearer key)
  * /register /login /logout — dashboard auth
  * /api/keys, /keys/*    — API-key management
  * /                     — dashboard (create keys, view quota + servers)
  * /health, /ready       — health probes
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from synapse_backend.api import routes_auth, routes_keys, routes_telemetry, routes_web
from synapse_backend.config import settings

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("synapse.api")

# Disable FastAPI's built-in /docs (Swagger) so /docs serves the marketing page.
# The OpenAPI schema stays available at /openapi.json.
app = FastAPI(title="Synapse API", version="0.1.0", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "web", "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

app.include_router(routes_telemetry.router)
app.include_router(routes_auth.router)
app.include_router(routes_keys.router)
app.include_router(routes_web.router)


@app.on_event("startup")
async def _startup() -> None:
    # Ensure tables exist (idempotent) so the API is usable without the init job.
    try:
        from synapse_backend.db.database import Base, sync_engine

        Base.metadata.create_all(bind=sync_engine)
    except Exception:  # noqa: BLE001
        logger.exception("table creation on startup failed")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "synapse-api"}


@app.get("/ready")
async def ready() -> dict:
    return {"status": "ready"}
