"""Endpoint detection — classify functions into MCP tool candidates.

Backs the ``DetectEndpoints`` RPC. Two implementations, chosen by config:

* **heuristic** (mock / fallback) — rule-based scoring from name, signature,
  docstring and return type. Deterministic, no API key.
* **llm** — asks the configured model to classify (see prompts.CLASSIFY_*).

Both return a list of dicts shaped like the ``DetectedEndpoint`` proto message.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from synapse_backend.agents import prompts
from synapse_backend.llm import LLMMessage, get_llm
from synapse_backend.llm.factory import is_mock

logger = logging.getLogger(__name__)

# Verb -> subcategory mapping for human-friendly labels.
_VERB_CATEGORY = {
    "get": "data-retrieval",
    "fetch": "data-retrieval",
    "load": "data-retrieval",
    "read": "data-retrieval",
    "list": "data-retrieval",
    "find": "search",
    "search": "search",
    "query": "search",
    "lookup": "search",
    "filter": "search",
    "create": "mutation",
    "add": "mutation",
    "insert": "mutation",
    "update": "mutation",
    "delete": "mutation",
    "remove": "mutation",
    "save": "mutation",
    "send": "mutation",
    "schedule": "mutation",
    "book": "mutation",
    "analyze": "analysis",
    "score": "analysis",
    "compute": "analysis",
    "calculate": "analysis",
    "predict": "analysis",
    "detect": "analysis",
    "rank": "analysis",
}

# First-parameter names that imply the function needs a client/connection wrapper.
_WRAPPER_HINTS = {"client", "conn", "connection", "session", "db", "cursor", "engine"}

# Names we never expose.
_SKIP_EXACT = {"main", "setup", "teardown", "run"}


def _first_word(name: str) -> str:
    return re.split(r"[_A-Z]", name, maxsplit=1)[0].lower() if name else ""


def _is_candidate(fn: dict[str, Any]) -> bool:
    name = fn.get("name", "")
    if not name or name.startswith("_"):
        return False
    if name.startswith("test_") or name in _SKIP_EXACT:
        return False
    if fn.get("endpoint_type") == "method" and name in {"__init__", "__call__"}:
        return False
    return True


def _score(fn: dict[str, Any]) -> float:
    """Heuristic confidence in [0, 1]."""
    score = 0.35
    name = fn.get("name", "")
    verb = _first_word(name)
    if verb in _VERB_CATEGORY:
        score += 0.25
    if fn.get("docstring"):
        score += 0.15
    if fn.get("param_names"):
        score += 0.1
    ret = fn.get("return_type", "")
    if ret and ret not in ("None", "", "Any"):
        score += 0.1
    if fn.get("endpoint_type") in ("route", "endpoint"):
        score += 0.15
    # Penalize very short/private-ish helpers.
    if len(name) <= 3:
        score -= 0.1
    return max(0.0, min(1.0, round(score, 3)))


def _conversion_type(fn: dict[str, Any]) -> tuple[str, str]:
    """Return (conversion_type, client_dependency_json)."""
    params = fn.get("param_names") or []
    first = params[0].lower() if params else ""
    if first in _WRAPPER_HINTS or (first == "self" and len(params) == 1):
        dep = {
            "client_name": params[0] if params else "client",
            "library": "",
            "env_vars": [],
        }
        return "requires_wrapper", json.dumps(dep)
    return "ready", ""


def _humanize(fn: dict[str, Any]) -> tuple[str, str]:
    name = fn.get("name", "")
    title = name.replace("_", " ").strip().title()
    doc = (fn.get("docstring") or "").strip()
    description = doc.split("\n", 1)[0].strip() if doc else f"Calls {name}()."
    return title, description


def heuristic_classify(functions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for fn in functions:
        if not _is_candidate(fn):
            continue
        verb = _first_word(fn.get("name", ""))
        conv, dep_json = _conversion_type(fn)
        title, desc = _humanize(fn)
        candidates.append(
            {
                "name": fn.get("name", ""),
                "file_path": fn.get("file_path", ""),
                "confidence": _score(fn),
                "human_title": title,
                "human_description": desc,
                "conversion_type": conv,
                "client_dependency_json": dep_json,
                "subcategory": _VERB_CATEGORY.get(verb, "action"),
                "signature": fn.get("signature", ""),
                "docstring": fn.get("docstring", ""),
                "line_number": int(fn.get("line_number", 0) or 0),
            }
        )
    candidates.sort(key=lambda c: c["confidence"], reverse=True)
    return candidates


def llm_classify(
    functions: list[dict[str, Any]], project_schema: str
) -> list[dict[str, Any]]:
    llm = get_llm()
    messages = [
        LLMMessage(role="system", content=prompts.CLASSIFY_SYSTEM),
        LLMMessage(
            role="user",
            content=prompts.CLASSIFY_USER.format(
                project_schema=project_schema[:6000],
                functions_json=json.dumps(functions, indent=2)[:20000],
            ),
        ),
    ]
    data = llm.complete_json(messages)
    if isinstance(data, dict):
        data = data.get("candidates", [])
    results: list[dict[str, Any]] = []
    # Index source functions for filling missing fields.
    by_name = {f.get("name"): f for f in functions}
    for item in data if isinstance(data, list) else []:
        src = by_name.get(item.get("name"), {})
        results.append(
            {
                "name": item.get("name", ""),
                "file_path": item.get("file_path") or src.get("file_path", ""),
                "confidence": float(item.get("confidence", 0.6)),
                "human_title": item.get("human_title", item.get("name", "")),
                "human_description": item.get("human_description", ""),
                "conversion_type": item.get("conversion_type", "ready"),
                "client_dependency_json": item.get("client_dependency_json", ""),
                "subcategory": item.get("subcategory", "action"),
                "signature": item.get("signature") or src.get("signature", ""),
                "docstring": item.get("docstring") or src.get("docstring", ""),
                "line_number": int(
                    item.get("line_number", src.get("line_number", 0)) or 0
                ),
            }
        )
    results.sort(key=lambda c: c["confidence"], reverse=True)
    return results


def detect(
    functions: list[dict[str, Any]], project_schema: str = ""
) -> list[dict[str, Any]]:
    """Classify functions into MCP tool candidates (LLM if configured, else heuristic)."""
    if is_mock():
        return heuristic_classify(functions)
    try:
        result = llm_classify(functions, project_schema)
        # If the model returned nothing useful, fall back so the CLI still works.
        return result or heuristic_classify(functions)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM classify failed (%s) — using heuristic.", exc)
        return heuristic_classify(functions)
