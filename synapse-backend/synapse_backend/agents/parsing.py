"""Pure parsing helpers (no LLM/vector/DB imports, so they're easily testable).

Turns the CLI's build inputs — the '### Function:' markdown query blocks and the
JSON context_bundle — into normalized function records.
"""

from __future__ import annotations

import re
from typing import Any

_FUNC_BLOCK_RE = re.compile(
    r"###\s*Function:\s*`?(?P<name>[\w.]+)`?(?P<body>.*?)(?=(?:\n###\s*Function:)|\Z)",
    re.DOTALL,
)


def _field(body: str, label: str) -> str:
    m = re.search(rf"-\s*{label}:\s*`?(?P<v>[^\n`]+)`?", body, re.IGNORECASE)
    return m.group("v").strip() if m else ""


def normalize_fn(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": item.get("name", ""),
        "file_path": item.get("file_path", ""),
        "signature": item.get("signature", ""),
        "docstring": item.get("docstring", ""),
        "return_type": item.get("return_type", ""),
        "conversion_type": item.get("conversion_type", "ready"),
        "param_names": item.get("param_names", []),
        "line_number": item.get("line_number", 0),
    }


def parse_functions_from_query(query: str) -> list[dict[str, Any]]:
    """Extract structured functions from the CLI's '### Function:' query blocks."""
    functions: list[dict[str, Any]] = []
    for m in _FUNC_BLOCK_RE.finditer(query or ""):
        body = m.group("body")
        functions.append(
            {
                "name": m.group("name"),
                "file_path": _field(body, "File"),
                "signature": _field(body, "Signature"),
                "docstring": _field(body, "Description"),
                "return_type": _field(body, "Return Type"),
                "conversion_type": (_field(body, "Conversion Type") or "ready").lower(),
                "param_names": [],
                "line_number": 0,
            }
        )
    return functions


def parse_functions_from_bundle(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Pull functions out of the CLI-provided context_bundle (shape-tolerant)."""
    if not isinstance(bundle, dict):
        return []
    functions: list[dict[str, Any]] = []
    for key in ("functions", "endpoints", "selected_endpoints", "candidates"):
        val = bundle.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("name"):
                    functions.append(normalize_fn(item))
    return functions
