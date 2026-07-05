"""Supplier risk scoring — a sample 'locked-in' enterprise module.

This is demo code for testing Synapse end-to-end: point the CLI (or the
build-from-dir script) at this project and Synapse will detect these functions
as MCP tool candidates and generate a server that exposes them.
"""

from __future__ import annotations


def get_supplier_risk(supplier_id: str, fiscal_year: int, region: str = "") -> dict:
    """Calculate a comprehensive risk score for a supplier.

    Combines financial, geopolitical and delivery signals into a 0-100 score.
    """
    base = (hash(supplier_id) % 40) + 40
    return {
        "supplier_id": supplier_id,
        "fiscal_year": fiscal_year,
        "region": region or "global",
        "risk_score": base,
        "breakdown": {"financial": base + 8, "geopolitical": base - 7, "delivery": base},
    }


def get_delivery_performance(supplier_id: str, months: int = 12) -> dict:
    """Return on-time delivery metrics for a supplier over the last N months."""
    return {
        "supplier_id": supplier_id,
        "on_time_rate": 0.92,
        "avg_delay_days": 1.4,
        "window_months": months,
    }


def list_high_risk_suppliers(threshold: int = 70, region: str = "") -> list:
    """List suppliers whose risk score exceeds a threshold."""
    return [
        {"supplier_id": "SUP-45678", "risk_score": 72, "region": region or "EU"},
        {"supplier_id": "SUP-11234", "risk_score": 81, "region": region or "APAC"},
    ]


def _normalize_score(raw: float) -> float:
    """Internal helper — should NOT be exposed as a tool."""
    return max(0.0, min(100.0, raw))
