"""Inventory queries: stock per SKU, low stock, and at-risk orders."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from orderbridge.events.outbox import add_event
from orderbridge.models import (
    Inventory,
    Order,
    OrderLine,
    Product,
    PurchaseOrder,
    ReplenishmentProposal,
)
from orderbridge.services.errors import InvalidInputError, NotFoundError

# Orders that still need stock reserved for them.
UNALLOCATED_STATUSES = ("RECEIVED", "ACKNOWLEDGED")


def normalise_sku(sku: str) -> str:
    return (sku or "").strip().upper()


def db_today(session: Session) -> date:
    """Today's date according to the database, so all date maths agree with the seed data."""
    return session.scalar(select(func.current_date()))


def get_product(session: Session, sku: str) -> Product:
    """Return the product or raise a clear 'unknown SKU' error."""
    product = session.get(Product, normalise_sku(sku))
    if product is None:
        raise NotFoundError(f"Unknown SKU '{sku}'. Check the SKU and try again.")
    return product


def unknown_skus(session: Session, skus: Iterable[str]) -> list[str]:
    """Which of these SKUs are not in the item master?"""
    wanted = {normalise_sku(s) for s in skus}
    known = set(session.scalars(select(Product.sku).where(Product.sku.in_(wanted))))
    return sorted(wanted - known)


def available_by_sku(session: Session, skus: Iterable[str]) -> dict[str, int]:
    """Total available (on_hand - allocated) across all warehouses, per SKU."""
    skus = list({normalise_sku(s) for s in skus})
    rows = session.execute(
        select(Inventory.sku, func.sum(Inventory.on_hand - Inventory.allocated))
        .where(Inventory.sku.in_(skus))
        .group_by(Inventory.sku)
    )
    result = {sku: 0 for sku in skus}
    result.update({sku: int(total) for sku, total in rows})
    return result


def _open_demand(session: Session, skus: list[str]) -> dict[str, int]:
    """Quantity on orders that are not yet allocated, per SKU."""
    rows = session.execute(
        select(OrderLine.sku, func.sum(OrderLine.qty))
        .join(Order)
        .where(OrderLine.sku.in_(skus), Order.status.in_(UNALLOCATED_STATUSES))
        .group_by(OrderLine.sku)
    )
    return {sku: int(qty) for sku, qty in rows}


def _pending_replenishment(session: Session, skus: list[str]) -> dict[str, int]:
    rows = session.execute(
        select(ReplenishmentProposal.sku, func.sum(ReplenishmentProposal.qty))
        .where(ReplenishmentProposal.sku.in_(skus), ReplenishmentProposal.status == "PENDING")
        .group_by(ReplenishmentProposal.sku)
    )
    return {sku: int(qty) for sku, qty in rows}


def _open_purchase_orders(session: Session, skus: list[str]) -> dict[str, int]:
    rows = session.execute(
        select(PurchaseOrder.sku, func.sum(PurchaseOrder.qty))
        .where(PurchaseOrder.sku.in_(skus), PurchaseOrder.status == "OPEN")
        .group_by(PurchaseOrder.sku)
    )
    return {sku: int(qty) for sku, qty in rows}


def inventory_snapshot(session: Session, sku: str) -> dict[str, Any]:
    """On hand, allocated and available per warehouse, plus demand and supply context."""
    product = get_product(session, sku)
    warehouses = [
        {
            "warehouse": inv.warehouse,
            "on_hand": inv.on_hand,
            "allocated": inv.allocated,
            "available": inv.available,
        }
        for inv in product.inventory
    ]
    total_available = sum(w["available"] for w in warehouses)
    skus = [product.sku]
    return {
        "sku": product.sku,
        "description": product.description,
        "warehouses": warehouses,
        "total_on_hand": sum(w["on_hand"] for w in warehouses),
        "total_allocated": sum(w["allocated"] for w in warehouses),
        "total_available": total_available,
        "reorder_point": product.reorder_point,
        "reorder_qty": product.reorder_qty,
        "lead_time_days": product.lead_time_days,
        "below_reorder_point": total_available <= product.reorder_point,
        "unallocated_order_demand": _open_demand(session, skus).get(product.sku, 0),
        "pending_replenishment_qty": _pending_replenishment(session, skus).get(product.sku, 0),
        "open_purchase_order_qty": _open_purchase_orders(session, skus).get(product.sku, 0),
    }


def list_low_stock(session: Session) -> list[dict[str, Any]]:
    """SKUs whose total available stock is at or below their reorder point."""
    available = func.sum(Inventory.on_hand - Inventory.allocated)
    rows = session.execute(
        select(Product, func.sum(Inventory.on_hand), available)
        .join(Inventory)
        .group_by(Product.sku)
        .having(available <= Product.reorder_point)
        .order_by(Product.sku)
    ).all()
    skus = [p.sku for p, _, _ in rows]
    demand = _open_demand(session, skus)
    pending = _pending_replenishment(session, skus)
    open_po = _open_purchase_orders(session, skus)
    result = []
    for product, on_hand, avail in rows:
        avail = int(avail)
        sku_demand = demand.get(product.sku, 0)
        # Enough to cover waiting orders and get back above the reorder point,
        # and never less than the standard reorder quantity.
        suggested = max(product.reorder_qty, sku_demand + product.reorder_point - avail)
        result.append(
            {
                "sku": product.sku,
                "description": product.description,
                "on_hand": int(on_hand),
                "available": avail,
                "reorder_point": product.reorder_point,
                "reorder_qty": product.reorder_qty,
                "lead_time_days": product.lead_time_days,
                "unallocated_order_demand": sku_demand,
                "pending_replenishment_qty": pending.get(product.sku, 0),
                "open_purchase_order_qty": open_po.get(product.sku, 0),
                "suggested_order_qty": suggested,
            }
        )
    return result


def find_at_risk_orders(session: Session, days: int = 2) -> list[dict[str, Any]]:
    """Unallocated orders due to ship within `days` days (or overdue), with the reasons."""
    if not 0 <= days <= 30:
        raise InvalidInputError("days must be between 0 and 30.")
    today = db_today(session)
    orders = session.scalars(
        select(Order)
        .options(selectinload(Order.lines), selectinload(Order.partner))
        .where(
            Order.status.in_(UNALLOCATED_STATUSES),
            Order.requested_ship_date.is_not(None),
            Order.requested_ship_date <= func.current_date() + days,
        )
        .order_by(Order.requested_ship_date, Order.po_number)
    ).all()
    all_skus = {line.sku for o in orders for line in o.lines}
    available = available_by_sku(session, all_skus) if all_skus else {}

    results = []
    for order in orders:
        days_left = (order.requested_ship_date - today).days
        if days_left < 0:
            reasons = [f"Overdue: was due to ship {-days_left} day(s) ago and is not allocated."]
        elif days_left == 0:
            reasons = ["Due to ship today and is not allocated yet."]
        else:
            reasons = [f"Due to ship in {days_left} day(s) and is not allocated yet."]

        needed: dict[str, int] = defaultdict(int)
        for line in order.lines:
            needed[line.sku] += line.qty
        short_lines = []
        for sku, qty in needed.items():
            if qty > available.get(sku, 0):
                short_lines.append(
                    {
                        "sku": sku,
                        "needed": qty,
                        "available": available.get(sku, 0),
                        "short_by": qty - available.get(sku, 0),
                    }
                )
                reasons.append(
                    f"Short on {sku}: needs {qty}, only {available.get(sku, 0)} available."
                )
        results.append(
            {
                "order_id": order.id,
                "po_number": order.po_number,
                "partner_code": order.partner.code,
                "partner_name": order.partner.name,
                "status": order.status,
                "requested_ship_date": order.requested_ship_date.isoformat(),
                "days_until_ship": days_left,
                "lines": [{"sku": l.sku, "qty": l.qty} for l in order.lines],
                "can_fully_allocate": not short_lines,
                "short_lines": short_lines,
                "reasons": reasons,
            }
        )
    return results


def inventory_changed_event(session: Session, inv: Inventory, reason: str) -> None:
    """Stage an inventory.changed event for one SKU/warehouse row."""
    add_event(
        session,
        "inventory.changed",
        inv.sku,
        {
            "sku": inv.sku,
            "warehouse": inv.warehouse,
            "on_hand": inv.on_hand,
            "allocated": inv.allocated,
            "available": inv.available,
            "reason": reason,
        },
    )
