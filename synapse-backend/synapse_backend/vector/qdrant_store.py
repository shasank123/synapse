"""Server-side semantic index over functions (Qdrant + fastembed).

The doc's RAG pipeline embeds every function and stores it in Qdrant so the
Planner can retrieve the most relevant functions for a build query. The CLI
also does local indexing, but the backend keeps its own per-request index so
DetectEndpoints / Build can rank functions semantically without round-tripping.

Embeddings use fastembed (BAAI/bge-small-en-v1.5, 384-dim) — CPU-only, no API
key. Everything fails soft: if Qdrant/embeddings are unavailable, callers fall
back to lexical ranking.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Any, Iterable

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from synapse_backend.config import settings

logger = logging.getLogger(__name__)


@lru_cache
def _embedder():
    """Lazily construct the fastembed model (downloads once, then cached)."""
    from fastembed import TextEmbedding

    return TextEmbedding(model_name="BAAI/bge-small-en-v1.5")


@lru_cache
def _client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url, timeout=30)


def embed(texts: list[str]) -> list[list[float]]:
    return [list(v) for v in _embedder().embed(texts)]


def ensure_collection(collection: str | None = None) -> bool:
    """Create the collection if missing. Returns True on success."""
    name = collection or settings.qdrant_collection
    try:
        client = _client()
        if not client.collection_exists(name):
            client.create_collection(
                collection_name=name,
                vectors_config=qmodels.VectorParams(
                    size=settings.embedding_dim,
                    distance=qmodels.Distance.COSINE,
                ),
            )
            logger.info("Created Qdrant collection %s", name)
        return True
    except Exception as exc:  # noqa: BLE001 - fail soft
        logger.warning("ensure_collection failed: %s", exc)
        return False


def _function_text(fn: dict[str, Any]) -> str:
    """Build the text we embed for a function record."""
    return "\n".join(
        p
        for p in (
            fn.get("name", ""),
            fn.get("signature", ""),
            fn.get("docstring", ""),
            fn.get("return_type", ""),
        )
        if p
    )


def index_functions(
    functions: Iterable[dict[str, Any]], namespace: str, collection: str | None = None
) -> int:
    """Embed and upsert functions under a namespace (e.g. working_dir hash).

    Returns the number of points indexed; 0 on failure.
    """
    name = collection or settings.qdrant_collection
    funcs = list(functions)
    if not funcs:
        return 0
    if not ensure_collection(name):
        return 0
    try:
        vectors = embed([_function_text(f) for f in funcs])
        points = [
            qmodels.PointStruct(
                id=str(uuid.uuid4()),
                vector=vec,
                payload={**fn, "namespace": namespace},
            )
            for fn, vec in zip(funcs, vectors)
        ]
        _client().upsert(collection_name=name, points=points)
        return len(points)
    except Exception as exc:  # noqa: BLE001
        logger.warning("index_functions failed: %s", exc)
        return 0


def search(
    query: str,
    namespace: str,
    limit: int = 15,
    collection: str | None = None,
) -> list[dict[str, Any]]:
    """Return the most relevant function payloads for a query within a namespace."""
    name = collection or settings.qdrant_collection
    try:
        qvec = embed([query])[0]
        hits = _client().search(
            collection_name=name,
            query_vector=qvec,
            limit=limit,
            query_filter=qmodels.Filter(
                must=[
                    qmodels.FieldCondition(
                        key="namespace",
                        match=qmodels.MatchValue(value=namespace),
                    )
                ]
            ),
        )
        results = []
        for h in hits:
            payload = dict(h.payload or {})
            payload["_score"] = h.score
            results.append(payload)
        return results
    except Exception as exc:  # noqa: BLE001
        logger.warning("search failed: %s", exc)
        return []
