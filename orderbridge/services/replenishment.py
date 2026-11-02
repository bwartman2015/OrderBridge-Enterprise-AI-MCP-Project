"""Replenishment: propose (AI or human) and decide (human only).

Segregation of duties: `propose_replenishment` is exposed to the AI through MCP.
`decide_proposal` is used only by the human approval CLI and is deliberately NOT
exposed as an MCP tool, so the AI can suggest spending money but never approve it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from orderbridge.events.outbox import add_event
from orderbridge.models import Product, PurchaseOrder, ReplenishmentProposal
from orderbridge.services.errors import ConflictError, InvalidInputError, NotFoundError
from orderbridge.services.inventory import db_today, get_product

# Guardrail: anything above 10x the normal reorder quantity is treated as a mistake.
MAX_REORDER_MULTIPLIER = 10


def validate_quantity(product: Product, qty: Any) -> int:
    """Reject non-integers, zero/negative numbers, and absurdly large quantities."""
    if isinstance(qty, bool) or not isinstance(qty, int):
        raise InvalidInputError(f"Quantity must be a whole number, got {qty!r}.")
    if qty <= 0:
        raise InvalidInputError(f"Quantity must be greater than 0, got {qty}.")
    limit = product.reorder_qty * MAX_REORDER_MULTIPLIER
    if qty > limit:
        raise InvalidInputError(
            f"Quantity {qty} is not reasonable for {product.sku}: the limit is "
            f"{MAX_REORDER_MULTIPLIER} x its reorder quantity of {product.reorder_qty} = {limit}."
        )
    return qty


def proposal_to_dict(p: ReplenishmentProposal) -> dict[str, Any]:
    return {
        "id": p.id,
        "sku": p.sku,
        "qty": p.qty,
        "reason": p.reason,
        "proposed_by": p.proposed_by,
        "status": p.status,
        "decided_by": p.decided_by,
        "decided_at": p.decided_at.isoformat() if p.decided_at else None,
        "decision_note": p.decision_note,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def purchase_order_to_dict(po: PurchaseOrder) -> dict[str, Any]:
    return {
        "id": po.id,
        "po_number": po.po_number,
        "proposal_id": po.proposal_id,
        "sku": po.sku,
        "qty": po.qty,
        "unit_cost": float(po.unit_cost),
        "total_cost": float(po.unit_cost * po.qty),
        "status": po.status,
        "approved_by": po.approved_by,
        "expected_date": po.expected_date.isoformat() if po.expected_date else None,
        "created_at": po.created_at.isoformat() if po.created_at else None,
    }


def propose_replenishment(
    session: Session, sku: str, qty: Any, reason: str, proposed_by: str
) -> ReplenishmentProposal:
    """Create a PENDING proposal. This never creates a purchase order."""
    product = get_product(session, sku)  # unknown SKU -> NotFoundError
    qty = validate_quantity(product, qty)
    reason = (reason or "").strip()
    if not reason:
        raise InvalidInputError("A reason is required so the approver knows why.")
    if len(reason) > 500:
        raise InvalidInputError("Reason must be 500 characters or fewer.")

    already_pending = session.scalar(
        select(ReplenishmentProposal).where(
            ReplenishmentProposal.sku == product.sku, ReplenishmentProposal.status == "PENDING"
        )
    )
    if already_pending:
        raise ConflictError(
            f"Proposal #{already_pending.id} for {product.sku} (qty {already_pending.qty}) is "
            "already waiting for human approval. Do not create another one."
        )

    proposal = ReplenishmentProposal(
        sku=product.sku, qty=qty, reason=reason, proposed_by=proposed_by, status="PENDING"
    )
    session.add(proposal)
    session.flush()
    session.refresh(proposal)
    add_event(session, "replenishment.proposed", product.sku, proposal_to_dict(proposal))
    return proposal


def list_proposals(session: Session, status: str | None = "PENDING") -> list[ReplenishmentProposal]:
    query = select(ReplenishmentProposal).order_by(ReplenishmentProposal.id)
    if status:
        query = query.where(ReplenishmentProposal.status == status)
    return list(session.scalars(query))


def decide_proposal(
    session: Session, proposal_id: int, approve: bool, decided_by: str, note: str | None = None
) -> tuple[ReplenishmentProposal, PurchaseOrder | None]:
    """Approve (creates a purchase order) or reject a pending proposal. Humans only."""
    decided_by = (decided_by or "").strip()
    if not decided_by:
        raise InvalidInputError("The approver's name is required.")
    proposal = session.get(ReplenishmentProposal, proposal_id, with_for_update=True)
    if proposal is None:
        raise NotFoundError(f"Proposal #{proposal_id} not found.")
    if proposal.status != "PENDING":
        raise ConflictError(
            f"Proposal #{proposal_id} was already {proposal.status} by {proposal.decided_by}."
        )

    proposal.status = "APPROVED" if approve else "REJECTED"
    proposal.decided_by = decided_by
    proposal.decided_at = datetime.now(timezone.utc)
    proposal.decision_note = (note or "").strip()[:500] or None

    purchase_order = None
    if approve:
        product = proposal.product
        po_id = session.scalar(text("SELECT nextval('purchase_orders_id_seq')"))
        purchase_order = PurchaseOrder(
            id=po_id,
            po_number=f"RPO-{po_id:06d}",
            proposal_id=proposal.id,
            sku=product.sku,
            qty=proposal.qty,
            unit_cost=product.unit_cost,
            status="OPEN",
            approved_by=decided_by,
            expected_date=db_today(session) + timedelta(days=product.lead_time_days),
        )
        session.add(purchase_order)
        session.flush()
        session.refresh(purchase_order)
        add_event(
            session,
            "replenishment.approved",
            proposal.sku,
            {**proposal_to_dict(proposal), "purchase_order_number": purchase_order.po_number},
        )
        add_event(
            session,
            "purchase_order.created",
            purchase_order.po_number,
            purchase_order_to_dict(purchase_order),
        )
    else:
        add_event(session, "replenishment.rejected", proposal.sku, proposal_to_dict(proposal))
    return proposal, purchase_order
