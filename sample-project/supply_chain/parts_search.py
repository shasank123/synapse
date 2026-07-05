"""Parts catalog search — sample module."""

from __future__ import annotations


def search_parts(query: str, region: str = "", max_results: int = 10) -> list:
    """Search for parts across suppliers matching a text query.

    Returns a ranked list of matching parts with supplier and price info.
    """
    return [
        {"part": f"{query}-A1", "supplier_id": "SUP-45678", "price": 12.5, "region": region},
        {"part": f"{query}-B2", "supplier_id": "SUP-11234", "price": 13.9, "region": region},
    ][:max_results]


def get_part_availability(part_number: str, warehouse: str = "") -> dict:
    """Check stock availability for a specific part across warehouses."""
    return {"part_number": part_number, "in_stock": 340, "warehouse": warehouse or "central"}


def create_purchase_order(supplier_id: str, part_number: str, quantity: int) -> dict:
    """Create a purchase order for a part from a supplier."""
    return {
        "po_id": f"PO-{abs(hash((supplier_id, part_number))) % 100000}",
        "supplier_id": supplier_id,
        "part_number": part_number,
        "quantity": quantity,
        "status": "created",
    }
