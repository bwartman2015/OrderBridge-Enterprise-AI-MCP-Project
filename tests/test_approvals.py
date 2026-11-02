"""Human approval workflow (scripts/approve.py and the decide service)."""

import subprocess
import sys

import pytest
from sqlalchemy import select

from orderbridge.config import PROJECT_ROOT
from orderbridge.db import new_session, session_scope
from orderbridge.models import PurchaseOrder, ReplenishmentProposal
from orderbridge.services.errors import ConflictError
from orderbridge.services.replenishment import decide_proposal, propose_replenishment
from tests.helpers import audit_rows, outbox_types


def _propose():
    with session_scope() as s:
        return propose_replenishment(s, "FUEL-230", 400, "Low stock", "claude via MCP").id


def test_approve_creates_purchase_order_and_events(db):
    pid = _propose()
    with session_scope() as s:
        proposal, po = decide_proposal(s, pid, True, "morgan")
    assert proposal.status == "APPROVED" and proposal.decided_by == "morgan"
    assert po.po_number.startswith("RPO-") and po.qty == 400 and po.approved_by == "morgan"
    assert outbox_types()[-2:] == ["replenishment.approved", "purchase_order.created"]


def test_reject_creates_no_purchase_order(db):
    pid = _propose()
    with session_scope() as s:
        decide_proposal(s, pid, False, "morgan", "Not needed")
    with new_session() as s:
        assert s.scalar(select(PurchaseOrder).where(PurchaseOrder.proposal_id == pid)) is None
    assert outbox_types()[-1] == "replenishment.rejected"


def test_cannot_decide_twice(db):
    pid = _propose()
    with session_scope() as s:
        decide_proposal(s, pid, True, "morgan")
    with pytest.raises(ConflictError, match="already APPROVED"):
        with session_scope() as s:
            decide_proposal(s, pid, False, "someone-else")


def test_cli_approve_records_approver(db):
    pid = _propose()
    out = subprocess.run(
        [sys.executable, "scripts/approve.py", "--approve", str(pid), "--as", "brad"],
        cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
    )  # fmt: skip
    assert out.returncode == 0, out.stderr
    assert "created purchase order RPO-" in out.stdout
    with new_session() as s:
        p = s.get(ReplenishmentProposal, pid)
        assert p.status == "APPROVED" and p.decided_by == "brad"
    last = audit_rows()[-1]
    assert (last.actor, last.role, last.tool_or_endpoint, last.result) == ("brad", "approver", "approve.py", "OK")


def test_cli_list(db):
    _propose()
    out = subprocess.run(
        [sys.executable, "scripts/approve.py", "--list"], cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60
    )
    assert "FUEL-230" in out.stdout and "1 pending proposal" in out.stdout
