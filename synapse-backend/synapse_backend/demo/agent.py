"""The Assistant: natural-language question -> tool call -> natural-language answer.

Two implementations (same as the rest of the platform):
* heuristic (mock / default): keyword intent + entity extraction, templated NL.
* llm: the configured model routes to a tool and phrases the answer.

Returns a dict: {answer, tool, args, result, trace}. ``trace`` is the
"Claude → MCP Server → tool(args)" line shown in the chat for transparency.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from synapse_backend.demo.tools import TOOLS, TOOLS_BY_NAME
from synapse_backend.llm import LLMMessage, get_llm
from synapse_backend.llm.factory import is_mock

logger = logging.getLogger(__name__)

_REGIONS = {"eu": "EU", "europe": "EU", "apac": "APAC", "asia": "APAC",
            "na": "NA", "north america": "NA", "us": "NA"}


# ── entity extraction ────────────────────────────────────────────────────────
def _supplier_id(msg: str) -> str | None:
    m = re.search(r"\bSUP-\d+\b", msg, re.IGNORECASE)
    return m.group(0).upper() if m else None


def _part_number(msg: str) -> str | None:
    # First identifier that is NOT a supplier id (SUP-...).
    for m in re.finditer(r"\b[A-Z]{2,}-?\d{2,}\b", msg):
        if not m.group(0).upper().startswith("SUP"):
            return m.group(0)
    return None


def _region(msg: str) -> str:
    low = msg.lower()
    for key, val in _REGIONS.items():
        if key in low:
            return val
    return ""


def _int_after(msg: str, words: list[str], default: int) -> int:
    # Strip identifier tokens (SUP-123, BRK-2201) so their digits aren't mistaken
    # for a quantity/threshold/month value.
    cleaned = re.sub(r"\b[A-Z]{2,}-?\d{2,}\b", " ", msg)
    for w in words:
        m = re.search(rf"{w}\D{{0,12}}(\d+)", cleaned, re.IGNORECASE)
        if m:
            return int(m.group(1))
    m = re.search(r"\b(\d{1,6})\b", cleaned)
    return int(m.group(1)) if m else default


def _search_query(msg: str) -> str:
    m = re.search(r"(?:parts?|search|find|for|alternative[s]?)\s+(?:for\s+)?([\w\s]{3,40})", msg, re.IGNORECASE)
    if m:
        q = re.sub(r"\b(in|near|under|below|with|the|a|an|please|suppliers?)\b.*$", "", m.group(1), flags=re.IGNORECASE)
        # Drop leading filler words so "parts for brake pads" -> "brake pads".
        q = re.sub(r"^(?:parts?|for|search|find|me|some|any)\s+", "", q.strip(), flags=re.IGNORECASE)
        q = re.sub(r"^(?:parts?|for)\s+", "", q, flags=re.IGNORECASE)
        q = q.strip(" .,?")
        if q:
            return q
    return "parts"


# ── heuristic routing ────────────────────────────────────────────────────────
def _route(msg: str) -> tuple[str, dict] | None:
    low = msg.lower()
    sup = _supplier_id(msg)
    part = _part_number(msg)
    region = _region(msg)

    if any(k in low for k in ("purchase order", "create po", "raise a po", "order ", "buy ")) and sup:
        return "create_purchase_order", {
            "supplier_id": sup,
            "part_number": part or "PART-0001",
            "quantity": _int_after(msg, ["quantity", "qty", "units", "order"], 1),
        }
    if any(k in low for k in ("delivery", "on-time", "on time", "performance", "late", "delays")) and sup:
        return "get_delivery_performance", {"supplier_id": sup,
                                            "months": _int_after(msg, ["months", "last"], 12)}
    if any(k in low for k in ("high risk", "high-risk", "at risk", "at-risk", "riskiest", "most risky", "which suppliers")):
        return "list_high_risk_suppliers", {"threshold": _int_after(msg, ["above", "over", "threshold"], 70),
                                            "region": region}
    if any(k in low for k in ("availability", "in stock", "stock", "available")) and part:
        return "get_part_availability", {"part_number": part}
    if "risk" in low and sup:
        return "get_supplier_risk", {"supplier_id": sup, "region": region}
    if any(k in low for k in ("search", "find", "parts", "part ", "alternative", "catalog", "suppliers for")):
        return "search_parts", {"query": _search_query(msg), "region": region}
    if sup:  # a supplier id with no clear verb -> default to risk
        return "get_supplier_risk", {"supplier_id": sup, "region": region}
    return None


# ── NL answer templates (heuristic) ──────────────────────────────────────────
def _phrase(tool: str, args: dict, result: Any) -> str:
    if tool == "get_supplier_risk":
        r = result
        rec = ("I'd recommend close monitoring." if r["risk_score"] >= 70
               else "Overall this supplier looks stable.")
        return (f"Supplier {r['supplier_id']} has a risk score of "
                f"{r['risk_score']}/100 ({r['trend']}). Breakdown — Financial "
                f"{r['financial']}, Geopolitical {r['geopolitical']}, Delivery "
                f"{r['delivery']}. {rec}")
    if tool == "get_delivery_performance":
        r = result
        return (f"Over the last {r['window_months']} months, {r['supplier_id']} "
                f"delivered on time {r['on_time_rate']*100:.0f}% of the time across "
                f"{r['shipments']} shipments, averaging {r['avg_delay_days']} days of delay.")
    if tool == "list_high_risk_suppliers":
        if not result:
            return "Good news — no suppliers currently exceed that risk threshold."
        items = ", ".join(f"{s['supplier_id']} ({s['risk_score']}, {s['region']})" for s in result)
        return f"I found {len(result)} high-risk supplier(s): {items}."
    if tool == "search_parts":
        if not result:
            return "I couldn't find any matching parts."
        lines = "; ".join(f"{p['part']} from {p['supplier_id']} at ${p['price']} "
                          f"({p['lead_days']}d lead)" for p in result)
        return f"I found {len(result)} matching part(s): {lines}."
    if tool == "get_part_availability":
        r = result
        return (f"Part {r['part_number']} has {r['available']} units available "
                f"({r['in_stock']} in stock, {r['reserved']} reserved) at {r['warehouse']}.")
    if tool == "create_purchase_order":
        r = result
        return (f"Done — created purchase order {r['po_id']} for {r['quantity']}× "
                f"{r['part_number']} from {r['supplier_id']}. ETA {r['eta_days']} days.")
    return json.dumps(result)


_HELP = (
    "I'm your supply-chain assistant. I can answer things like:\n"
    "• \"What's the risk score for supplier SUP-45678?\"\n"
    "• \"Search parts for brake pads in the EU\"\n"
    "• \"Show me the high-risk suppliers\"\n"
    "• \"Delivery performance for SUP-11234\"\n"
    "• \"Check availability for part BRK-2201\"\n"
    "• \"Create a purchase order for SUP-45678, part BRK-2201, qty 500\""
)


def _run_tool(tool: str, args: dict) -> Any:
    t = TOOLS_BY_NAME[tool]
    # Only pass known params.
    allowed = t.input_schema.get("properties", {}).keys()
    clean = {k: v for k, v in args.items() if k in allowed and v not in (None, "")}
    return t.fn(**clean)


# ── LLM path ─────────────────────────────────────────────────────────────────
def _llm_answer(message: str) -> dict:
    llm = get_llm()
    tool_list = [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]
    router = llm.complete_json([
        LLMMessage(role="system", content=(
            "You route a user request to ONE tool from this list and extract its "
            "arguments. Respond with JSON {\"tool\": <name or null>, \"args\": {...}}. "
            "Use null if no tool fits.\nTools:\n" + json.dumps(tool_list))),
        LLMMessage(role="user", content=message),
    ])
    tool = (router or {}).get("tool")
    args = (router or {}).get("args", {}) or {}
    if not tool or tool not in TOOLS_BY_NAME:
        return {"answer": _HELP, "tool": None, "args": {}, "result": None, "trace": ""}
    result = _run_tool(tool, args)
    answer = llm.complete([
        LLMMessage(role="system", content=(
            "You are a helpful business assistant. Answer the user's question in 1-3 "
            "natural sentences using the tool result. Don't mention JSON or tools.")),
        LLMMessage(role="user", content=(
            f"Question: {message}\nTool {tool} returned: {json.dumps(result)}")),
    ])
    return {"answer": answer.strip(), "tool": tool, "args": args, "result": result,
            "trace": f"Assistant → MCP Server → {tool}({_args_str(args)})"}


def _args_str(args: dict) -> str:
    return ", ".join(f"{k}={v!r}" for k, v in args.items() if v not in (None, ""))


# ── public entry ─────────────────────────────────────────────────────────────
def answer(message: str) -> dict:
    message = (message or "").strip()
    if not message:
        return {"answer": _HELP, "tool": None, "args": {}, "result": None, "trace": ""}

    if not is_mock():
        try:
            return _llm_answer(message)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LLM assistant failed (%s) — heuristic fallback.", exc)

    routed = _route(message)
    if routed is None:
        return {"answer": _HELP, "tool": None, "args": {}, "result": None, "trace": ""}
    tool, args = routed
    result = _run_tool(tool, args)
    return {
        "answer": _phrase(tool, args, result),
        "tool": tool,
        "args": args,
        "result": result,
        "trace": f"Assistant → MCP Server → {tool}({_args_str(args)})",
    }
