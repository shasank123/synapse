"""Celery application + background tasks.

Per the doc's orchestration layer, heavy/async work runs on Celery workers off a
Redis broker. For the POC the synchronous gRPC path already returns results
inline; these tasks cover the async side: warming the semantic index and
rolling up analytics. They're safe to expand later.
"""

from __future__ import annotations

import logging

from celery import Celery

from synapse_backend.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "synapse",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_time_limit=600,
)


@celery_app.task(name="synapse.index_functions")
def index_functions_task(functions: list[dict], namespace: str) -> int:
    """Embed + upsert functions into Qdrant in the background."""
    from synapse_backend.vector.qdrant_store import index_functions

    count = index_functions(functions, namespace=namespace)
    logger.info("Indexed %d functions for namespace %s", count, namespace)
    return count


@celery_app.task(name="synapse.ping")
def ping() -> str:
    return "pong"
