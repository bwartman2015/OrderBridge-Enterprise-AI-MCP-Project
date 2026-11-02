"""Order endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from orderbridge.api import idempotency
from orderbridge.api.deps import get_actor, get_session
from orderbridge.api.schemas import OrderCreate, ShipRequest
from orderbridge.audit import record_audit
from orderbridge.edi.outbound import build_856_document, write_outbound
from orderbridge.services.errors import ConflictError, DomainError
from orderbridge.services.orders import (
    NewOrderLine,
    allocate_order,
    create_order,
    get_order,
    get_partner,
    list_orders,
    order_to_dict,
    ship_order,
)

router = APIRouter(prefix="/orders", tags=["orders"])


@router.get("", summary="List orders (newest first)")
def list_all(
    status: str | None = Query(None, description="RECEIVED, ACKNOWLEDGED, ALLOCATED, SHIPPED or CANCELLED"),
    partner_code: str | None = Query(None, description="SWIFT, PEAK or GRANITE"),
    limit: int = Query(50, ge=1, le=500),
    session: Session = Depends(get_session),
) -> list[dict]:
    return [order_to_dict(o, detail=False) for o in list_orders(session, status, partner_code, limit)]


@router.get("/{order_id}", summary="One order with lines, allocations and shipments")
def get_one(order_id: int, session: Session = Depends(get_session)) -> dict:
    return order_to_dict(get_order(session, order_id))


@router.post(
    "",
    status_code=201,
    summary="Create an order (requires an Idempotency-Key header)",
    responses={
        201: {"description": "Order created (or replayed from an earlier identical request)"},
        400: {"description": "Idempotency-Key header missing"},
        409: {"description": "Duplicate PO, or Idempotency-Key reused with a different body"},
        422: {"description": "Validation failed (unknown SKU, qty <= 0, ...)"},
    },
)
def create(
    body: OrderCreate,
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="Unique value per new order, e.g. a UUID. Retries must reuse the same value.",
    ),
    session: Session = Depends(get_session),
    actor: str = Depends(get_actor),
):
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(
            status_code=400,
            detail="Idempotency-Key header is required for POST /orders (use a new UUID per order).",
        )
    key = idempotency_key.strip()
    if len(key) > 100:
        raise HTTPException(status_code=400, detail="Idempotency-Key must be 100 characters or fewer.")

    payload = body.model_dump(mode="json")
    request_hash = idempotency.fingerprint(payload)
    audit_args = {"idempotency_key": key, **payload}

    previous = idempotency.find(session, key)
    if previous is not None:
        if previous.request_hash != request_hash:
            message = (
                f"Idempotency-Key '{key}' was already used with a different request body. "
                "Use a new key for a new order."
            )
            record_audit(actor, "api", "POST /orders", audit_args, "ERROR", message)
            raise HTTPException(status_code=409, detail=message)
        record_audit(actor, "api", "POST /orders", audit_args, "OK", "Idempotent replay of earlier response")
        return JSONResponse(
            previous.response, status_code=previous.status_code, headers={"Idempotent-Replayed": "true"}
        )

    try:
        partner = get_partner(session, body.partner_code)
        order = create_order(
            session,
            partner,
            body.po_number,
            body.requested_ship_date,
            [
                NewOrderLine(line_no=i, sku=line.sku, qty=line.qty, unit_price=line.unit_price)
                for i, line in enumerate(body.lines, start=1)
            ],
            source="API",
        )
        response = order_to_dict(order)
        idempotency.remember(session, key, request_hash, 201, response)
        session.commit()
    except DomainError as exc:
        session.rollback()
        record_audit(actor, "api", "POST /orders", audit_args, "ERROR", str(exc))
        raise
    except IntegrityError:
        # Two identical requests raced each other; the other one won. Replay its answer.
        session.rollback()
        previous = idempotency.find(session, key)
        if previous is not None and previous.request_hash == request_hash:
            return JSONResponse(
                previous.response, status_code=previous.status_code, headers={"Idempotent-Replayed": "true"}
            )
        raise ConflictError("Order could not be saved because of a concurrent duplicate request.")

    record_audit(actor, "api", "POST /orders", audit_args, "OK", f"Created order {order.id}")
    return JSONResponse(response, status_code=201)


@router.post("/{order_id}/allocate", summary="Reserve stock for an order (all lines or nothing)")
def allocate(order_id: int, session: Session = Depends(get_session), actor: str = Depends(get_actor)) -> dict:
    endpoint = f"POST /orders/{order_id}/allocate"
    try:
        result = allocate_order(session, get_order(session, order_id))
        session.commit()
    except DomainError as exc:
        session.rollback()
        record_audit(actor, "api", endpoint, {"order_id": order_id}, "ERROR", str(exc))
        raise
    record_audit(actor, "api", endpoint, {"order_id": order_id}, "OK", result.to_dict()["message"])
    return result.to_dict()


@router.post("/{order_id}/ship", summary="Ship an allocated order and generate an 856 ASN")
def ship(
    order_id: int,
    body: ShipRequest,
    session: Session = Depends(get_session),
    actor: str = Depends(get_actor),
) -> dict:
    endpoint = f"POST /orders/{order_id}/ship"
    args = {"order_id": order_id, **body.model_dump()}
    try:
        order = get_order(session, order_id)
        shipment = ship_order(session, order, body.carrier, body.tracking_number)
        asn = build_856_document(session, order, shipment)
        session.commit()
    except DomainError as exc:
        session.rollback()
        record_audit(actor, "api", endpoint, args, "ERROR", str(exc))
        raise
    path = write_outbound(asn)  # after commit: never send an ASN for a shipment that rolled back
    record_audit(actor, "api", endpoint, args, "OK", f"Shipped; 856 written to {path.name}")
    return {**order_to_dict(order), "asn_file": path.name}
