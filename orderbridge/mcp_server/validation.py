"""Guardrails: check AI-supplied arguments BEFORE any data is read or changed.

LLMs can hallucinate SKUs, PO numbers and quantities, so every argument is checked
against the system of record and sanity limits first.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from orderbridge.models import Order, Product
from orderbridge.services.errors import InvalidInputError
from orderbridge.services.inventory import get_product
from orderbridge.services.orders import find_order_by_po
from orderbridge.services.replenishment import validate_quantity


def require_known_sku(session: Session, sku: str) -> Product:
    """Unknown SKU -> clear error."""
    if not sku or not sku.strip():
        raise InvalidInputError("sku is required.")
    return get_product(session, sku)


def require_reasonable_qty(product: Product, qty: Any) -> int:
    """Positive whole number, and at most 10x the SKU's normal reorder quantity."""
    return validate_quantity(product, qty)


def require_known_po(session: Session, po_number: str, partner_code: str | None = None) -> Order:
    """Unknown or ambiguous PO number -> clear error."""
    return find_order_by_po(session, po_number, partner_code)


def require_int_in_range(name: str, value: Any, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise InvalidInputError(f"{name} must be a whole number from {low} to {high}, got {value!r}.")
    return value
