"""Order lifecycle: create -> acknowledge -> allocate -> ship.

Every state change stages an outbox event in the same transaction.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from orderbridge.events.outbox import add_event
from orderbridge.models import Inventory, Order, OrderAllocation, OrderLine, Partner, Shipment
from orderbridge.services.errors import ConflictError, InvalidInputError, NotFoundError
from orderbridge.services.inventory import (
    UNALLOCATED_STATUSES,
    inventory_changed_event,
    normalise_sku,
    unknown_skus,
)

ORDER_STATUSES = ("RECEIVED", "ACKNOWLEDGED", "ALLOCATED", "SHIPPED", "CANCELLED")


@dataclass
class NewOrderLine:
    """One requested line, before it is saved."""

    line_no: int
    sku: str
    qty: int
    unit_price: Decimal


# --------------------------------------------------------------------------- lookups


def get_partner(session: Session, code: str) -> Partner:
    partner = session.scalar(select(Partner).where(Partner.code == (code or "").strip().upper()))
    if partner is None:
        known = ", ".join(session.scalars(select(Partner.code).order_by(Partner.code)))
        raise NotFoundError(f"Unknown partner code '{code}'. Known partners: {known}.")
    return partner


def get_partner_by_isa_id(session: Session, isa_id: str) -> Partner | None:
    return session.scalar(select(Partner).where(Partner.edi_isa_id == isa_id.strip()))


def _order_query():
    return select(Order).options(
        selectinload(Order.partner),
        selectinload(Order.lines).selectinload(OrderLine.product),
        selectinload(Order.allocations),
        selectinload(Order.shipments),
    )


def get_order(session: Session, order_id: int) -> Order:
    order = session.scalar(_order_query().where(Order.id == order_id))
    if order is None:
        raise NotFoundError(f"Order {order_id} not found.")
    return order


def find_order_by_po(session: Session, po_number: str, partner_code: str | None = None) -> Order:
    """Find an order by PO number. PO numbers are unique per partner, not globally."""
    po = (po_number or "").strip()
    if not po:
        raise InvalidInputError("po_number is required.")
    query = _order_query().where(func.upper(Order.po_number) == po.upper())
    if partner_code:
        query = query.join(Partner).where(Partner.code == partner_code.strip().upper())
    matches = session.scalars(query).all()
    if not matches:
        raise NotFoundError(f"No order found with PO number '{po}'.")
    if len(matches) > 1:
        codes = ", ".join(o.partner.code for o in matches)
        raise InvalidInputError(
            f"PO number '{po}' exists for more than one partner ({codes}). Pass partner_code."
        )
    return matches[0]


def list_orders(
    session: Session, status: str | None = None, partner_code: str | None = None, limit: int = 50
) -> list[Order]:
    query = _order_query().order_by(Order.id.desc()).limit(max(1, min(limit, 500)))
    if status:
        status = status.strip().upper()
        if status not in ORDER_STATUSES:
            raise InvalidInputError(f"status must be one of {', '.join(ORDER_STATUSES)}.")
        query = query.where(Order.status == status)
    if partner_code:
        query = query.join(Partner).where(Partner.code == partner_code.strip().upper())
    return list(session.scalars(query))


# --------------------------------------------------------------------------- serialisation


def order_to_dict(order: Order, detail: bool = True) -> dict[str, Any]:
    """Plain-JSON view of an order (used by the API, MCP tools and events)."""
    data: dict[str, Any] = {
        "id": order.id,
        "po_number": order.po_number,
        "partner_code": order.partner.code,
        "partner_name": order.partner.name,
        "status": order.status,
        "requested_ship_date": order.requested_ship_date.isoformat()
        if order.requested_ship_date
        else None,
        "created_at": order.created_at.isoformat() if order.created_at else None,
        "line_count": len(order.lines),
        "total_qty": sum(line.qty for line in order.lines),
        "order_value": float(sum(line.qty * line.unit_price for line in order.lines)),
    }
    if detail:
        data["lines"] = [
            {
                "line_no": line.line_no,
                "sku": line.sku,
                "description": line.product.description if line.product else None,
                "qty": line.qty,
                "unit_price": float(line.unit_price),
            }
            for line in order.lines
        ]
        data["allocations"] = [
            {"line_no": a.line_no, "sku": a.sku, "warehouse": a.warehouse, "qty": a.qty}
            for a in order.allocations
        ]
        data["shipments"] = [
            {
                "id": s.id,
                "carrier": s.carrier,
                "tracking_number": s.tracking_number,
                "shipped_at": s.shipped_at.isoformat() if s.shipped_at else None,
            }
            for s in order.shipments
        ]
    return data


def _event_body(order: Order, **extra: Any) -> dict[str, Any]:
    body = {
        "order_id": order.id,
        "po_number": order.po_number,
        "partner_code": order.partner.code,
        "status": order.status,
        "requested_ship_date": order.requested_ship_date.isoformat()
        if order.requested_ship_date
        else None,
    }
    body.update(extra)
    return body


# --------------------------------------------------------------------------- create


def create_order(
    session: Session,
    partner: Partner,
    po_number: str,
    requested_ship_date: date | None,
    lines: Sequence[NewOrderLine],
    source: str,
) -> Order:
    """Validate and save a new order in RECEIVED status, and stage `order.received`."""
    po_number = (po_number or "").strip()
    if not po_number:
        raise InvalidInputError("po_number is required.")
    if not lines:
        raise InvalidInputError("An order needs at least one line.")
    seen_line_numbers = set()
    for line in lines:
        if line.qty <= 0:
            raise InvalidInputError(
                f"Line {line.line_no} ({line.sku}): qty must be greater than 0, got {line.qty}."
            )
        if line.line_no in seen_line_numbers:
            raise InvalidInputError(f"Line number {line.line_no} appears more than once.")
        seen_line_numbers.add(line.line_no)
    missing = unknown_skus(session, [line.sku for line in lines])
    if missing:
        raise InvalidInputError(f"Unknown SKU(s): {', '.join(missing)}.")

    existing = session.scalar(
        select(Order).where(Order.partner_id == partner.id, Order.po_number == po_number)
    )
    if existing is not None:
        raise ConflictError(
            f"Duplicate PO: {partner.code} already sent PO {po_number} "
            f"(order {existing.id}, status {existing.status})."
        )

    order = Order(
        partner=partner,
        po_number=po_number,
        status="RECEIVED",
        requested_ship_date=requested_ship_date,
        lines=[
            OrderLine(
                line_no=line.line_no,
                sku=normalise_sku(line.sku),
                qty=line.qty,
                unit_price=line.unit_price,
            )
            for line in lines
        ],
    )
    session.add(order)
    session.flush()  # assigns order.id
    add_event(
        session,
        "order.received",
        order.po_number,
        _event_body(
            order,
            source=source,
            lines=[{"line_no": l.line_no, "sku": l.sku, "qty": l.qty} for l in order.lines],
        ),
    )
    return order


def acknowledge_order(
    session: Session, order: Order, ack_type: str, rejected_skus: Sequence[str] = ()
) -> None:
    """Mark an order ACKNOWLEDGED after an 855 has been generated for it."""
    if order.status != "RECEIVED":
        raise ConflictError(f"Order {order.po_number} is {order.status}; only RECEIVED can be acknowledged.")
    order.status = "ACKNOWLEDGED"
    add_event(
        session,
        "order.acknowledged",
        order.po_number,
        _event_body(order, ack_type=ack_type, rejected_skus=list(rejected_skus)),
    )


# --------------------------------------------------------------------------- allocate


@dataclass
class AllocationResult:
    """Outcome of an allocation attempt. Nothing is reserved unless `allocated` is True."""

    allocated: bool
    order: Order
    shortages: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result = {
            "po_number": self.order.po_number,
            "partner_code": self.order.partner.code,
            "allocated": self.allocated,
            "status": self.order.status,
        }
        if self.allocated:
            result["allocations"] = [
                {"line_no": a.line_no, "sku": a.sku, "warehouse": a.warehouse, "qty": a.qty}
                for a in self.order.allocations
            ]
            result["message"] = f"Order {self.order.po_number} is fully allocated."
        else:
            result["shortages"] = self.shortages
            result["message"] = (
                f"Order {self.order.po_number} was NOT allocated: not enough stock. "
                "Nothing was reserved."
            )
        return result


def allocate_order(session: Session, order: Order) -> AllocationResult:
    """Reserve stock for every line, or nothing at all (all-or-nothing).

    Inventory rows are locked (SELECT ... FOR UPDATE) so two allocations running
    at the same time cannot promise the same units twice.
    """
    if order.status == "ALLOCATED":
        raise ConflictError(f"Order {order.po_number} is already allocated.")
    if order.status not in UNALLOCATED_STATUSES:
        raise ConflictError(
            f"Order {order.po_number} is {order.status}; only RECEIVED or ACKNOWLEDGED "
            "orders can be allocated."
        )

    needed: dict[str, int] = defaultdict(int)
    for line in order.lines:
        needed[line.sku] += line.qty

    rows = session.scalars(
        select(Inventory)
        .where(Inventory.sku.in_(needed))
        .order_by(Inventory.sku, Inventory.warehouse)
        .with_for_update()
    ).all()
    by_sku: dict[str, list[Inventory]] = defaultdict(list)
    for inv in rows:
        by_sku[inv.sku].append(inv)

    shortages = []
    for sku, qty in needed.items():
        available = sum(inv.available for inv in by_sku[sku])
        if available < qty:
            shortages.append(
                {"sku": sku, "needed": qty, "available": available, "short_by": qty - available}
            )
    if shortages:
        return AllocationResult(allocated=False, order=order, shortages=shortages)

    touched: dict[tuple[str, str], Inventory] = {}
    for line in order.lines:
        remaining = line.qty
        # Take from the warehouse with the most available stock first.
        for inv in sorted(by_sku[line.sku], key=lambda r: r.available, reverse=True):
            if remaining == 0:
                break
            take = min(remaining, inv.available)
            if take <= 0:
                continue
            inv.allocated += take
            remaining -= take
            order.allocations.append(
                OrderAllocation(line_no=line.line_no, sku=line.sku, warehouse=inv.warehouse, qty=take)
            )
            touched[(inv.sku, inv.warehouse)] = inv

    order.status = "ALLOCATED"
    session.flush()
    for inv in touched.values():
        inventory_changed_event(session, inv, f"allocated to order {order.po_number}")
    add_event(
        session,
        "order.allocated",
        order.po_number,
        _event_body(
            order,
            allocations=[
                {"line_no": a.line_no, "sku": a.sku, "warehouse": a.warehouse, "qty": a.qty}
                for a in order.allocations
            ],
        ),
    )
    return AllocationResult(allocated=True, order=order)


# --------------------------------------------------------------------------- ship


def ship_order(session: Session, order: Order, carrier: str, tracking_number: str) -> Shipment:
    """Ship an allocated order: stock leaves the building and a shipment is recorded.

    The caller generates the 856 ASN after committing (see orderbridge.edi.outbound).
    """
    carrier = (carrier or "").strip().upper()
    tracking_number = (tracking_number or "").strip()
    if not carrier or not tracking_number:
        raise InvalidInputError("carrier and tracking_number are required.")
    if order.status != "ALLOCATED":
        raise ConflictError(
            f"Order {order.po_number} is {order.status}; it must be ALLOCATED before it can ship."
        )

    touched: dict[tuple[str, str], Inventory] = {}
    for alloc in order.allocations:
        inv = session.get(Inventory, (alloc.sku, alloc.warehouse), with_for_update=True)
        inv.on_hand -= alloc.qty
        inv.allocated -= alloc.qty
        touched[(inv.sku, inv.warehouse)] = inv

    shipment = Shipment(order_id=order.id, carrier=carrier, tracking_number=tracking_number)
    session.add(shipment)
    order.status = "SHIPPED"
    session.flush()
    session.refresh(shipment)  # load shipped_at default from the database
    order.shipments.append(shipment)

    for inv in touched.values():
        inventory_changed_event(session, inv, f"shipped on order {order.po_number}")
    add_event(
        session,
        "order.shipped",
        order.po_number,
        _event_body(
            order,
            shipment_id=shipment.id,
            carrier=carrier,
            tracking_number=tracking_number,
        ),
    )
    return shipment
