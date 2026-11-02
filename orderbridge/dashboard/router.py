"""Dashboard routes: the HTML page and the JSON it polls every few seconds."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from orderbridge.api.deps import get_session
from orderbridge.audit import recent_audit_entries
from orderbridge.models import Order, OutboxEvent, PurchaseOrder
from orderbridge.services.inventory import find_at_risk_orders, list_low_stock
from orderbridge.services.orders import list_orders, order_to_dict
from orderbridge.services.replenishment import list_proposals, proposal_to_dict, purchase_order_to_dict

router = APIRouter(tags=["dashboard"])
PAGE = Path(__file__).with_name("dashboard.html")


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard_page() -> HTMLResponse:
    return HTMLResponse(PAGE.read_text(encoding="utf-8"))


@router.get("/dashboard/data", summary="Everything the live dashboard shows, in one call")
def dashboard_data(session: Session = Depends(get_session)) -> dict:
    status_counts = dict(session.execute(select(Order.status, func.count()).group_by(Order.status)).all())
    backlog = session.scalar(select(func.count()).where(OutboxEvent.published_at.is_(None)))
    last_published = session.scalar(select(func.max(OutboxEvent.published_at)))
    pending = []
    for p in list_proposals(session, "PENDING"):
        pending.append(
            {**proposal_to_dict(p), "estimated_cost": float(p.product.unit_cost * p.qty)}
        )
    purchase_orders = session.scalars(select(PurchaseOrder).order_by(PurchaseOrder.id.desc()).limit(5))
    return {
        "status_counts": status_counts,
        "at_risk_count": len(find_at_risk_orders(session, 2)),
        "recent_orders": [order_to_dict(o, detail=False) for o in list_orders(session, limit=12)],
        "low_stock": list_low_stock(session),
        "pending_approvals": pending,
        "purchase_orders": [purchase_order_to_dict(po) for po in purchase_orders],
        "audit": recent_audit_entries(session, 15),
        "outbox": {
            "unpublished": backlog,
            "last_published_at": last_published.isoformat() if last_published else None,
        },
    }
