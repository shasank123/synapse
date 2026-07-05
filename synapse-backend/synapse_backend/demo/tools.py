"""A deployed 'supply-chain' MCP server, represented as executable demo tools.

This is what a Synapse-generated server exposes at runtime. The Assistant (an
MCP host stand-in) calls these tools on the user's behalf. Functions return
deterministic mock data so the demo works offline; in production they'd be the
customer's real functions.

Each tool has: name, description, an input JSON-schema (for LLM tool-calling),
and a callable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


# Deterministic scores (stable across restarts; aligned with list_high_risk_suppliers).
_KNOWN_SCORES = {"SUP-45678": 72, "SUP-11234": 81, "SUP-99001": 76}


def _stable_score(supplier_id: str) -> int:
    if supplier_id in _KNOWN_SCORES:
        return _KNOWN_SCORES[supplier_id]
    return 45 + (sum(ord(c) for c in supplier_id) % 45)


# ── the underlying 'codebase' functions ──────────────────────────────────────
def get_supplier_risk(supplier_id: str, region: str = "", fiscal_year: int = 2026) -> dict:
    base = _stable_score(supplier_id)
    return {
        "supplier_id": supplier_id,
        "region": region or "global",
        "fiscal_year": fiscal_year,
        "risk_score": base,
        "financial": min(100, base + 12),
        "geopolitical": max(0, base - 9),
        "delivery": base + 2,
        "trend": "improving" if base < 65 else "watch",
    }


def get_delivery_performance(supplier_id: str, months: int = 12) -> dict:
    return {
        "supplier_id": supplier_id,
        "on_time_rate": 0.92,
        "avg_delay_days": 1.4,
        "shipments": 318,
        "window_months": months,
    }


def list_high_risk_suppliers(threshold: int = 70, region: str = "") -> list:
    data = [
        {"supplier_id": "SUP-11234", "risk_score": 81, "region": "APAC"},
        {"supplier_id": "SUP-45678", "risk_score": 72, "region": "EU"},
        {"supplier_id": "SUP-99001", "risk_score": 76, "region": "NA"},
    ]
    out = [s for s in data if s["risk_score"] >= threshold]
    if region:
        out = [s for s in out if s["region"].lower() == region.lower()] or out
    return out


def search_parts(query: str, region: str = "", max_results: int = 5) -> list:
    q = query or "part"
    rows = [
        {"part": f"{q} · Model A1", "supplier_id": "SUP-45678", "price": 12.5, "region": region or "EU", "lead_days": 5},
        {"part": f"{q} · Model B2", "supplier_id": "SUP-11234", "price": 13.9, "region": region or "APAC", "lead_days": 9},
        {"part": f"{q} · Model C3", "supplier_id": "SUP-99001", "price": 11.2, "region": region or "NA", "lead_days": 7},
    ]
    return rows[:max_results]


def get_part_availability(part_number: str, warehouse: str = "") -> dict:
    return {
        "part_number": part_number,
        "in_stock": 340,
        "reserved": 60,
        "available": 280,
        "warehouse": warehouse or "Central-DC",
    }


def create_purchase_order(supplier_id: str, part_number: str, quantity: int = 1) -> dict:
    return {
        "po_id": f"PO-{abs(hash((supplier_id, part_number))) % 100000:05d}",
        "supplier_id": supplier_id,
        "part_number": part_number,
        "quantity": quantity,
        "status": "created",
        "eta_days": 6,
    }


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    fn: Callable[..., Any]


TOOLS: list[Tool] = [
    Tool(
        "get_supplier_risk",
        "Get the overall risk score (0-100) and breakdown for a supplier by its ID.",
        {"type": "object",
         "properties": {"supplier_id": {"type": "string"}, "region": {"type": "string"},
                        "fiscal_year": {"type": "integer"}},
         "required": ["supplier_id"]},
        get_supplier_risk,
    ),
    Tool(
        "get_delivery_performance",
        "Get on-time delivery metrics for a supplier over recent months.",
        {"type": "object",
         "properties": {"supplier_id": {"type": "string"}, "months": {"type": "integer"}},
         "required": ["supplier_id"]},
        get_delivery_performance,
    ),
    Tool(
        "list_high_risk_suppliers",
        "List suppliers whose risk score is at or above a threshold, optionally by region.",
        {"type": "object",
         "properties": {"threshold": {"type": "integer"}, "region": {"type": "string"}},
         "required": []},
        list_high_risk_suppliers,
    ),
    Tool(
        "search_parts",
        "Search the parts catalog across suppliers for a text query (e.g. 'brake pads').",
        {"type": "object",
         "properties": {"query": {"type": "string"}, "region": {"type": "string"},
                        "max_results": {"type": "integer"}},
         "required": ["query"]},
        search_parts,
    ),
    Tool(
        "get_part_availability",
        "Check stock availability for a specific part number in warehouses.",
        {"type": "object",
         "properties": {"part_number": {"type": "string"}, "warehouse": {"type": "string"}},
         "required": ["part_number"]},
        get_part_availability,
    ),
    Tool(
        "create_purchase_order",
        "Create a purchase order for a part from a supplier.",
        {"type": "object",
         "properties": {"supplier_id": {"type": "string"}, "part_number": {"type": "string"},
                        "quantity": {"type": "integer"}},
         "required": ["supplier_id", "part_number"]},
        create_purchase_order,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
