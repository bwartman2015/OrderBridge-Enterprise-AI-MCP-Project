"""MCP tool tests: authorization, validation, audit, and the propose-never-approve rule."""

import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from orderbridge.mcp_server import server
from orderbridge.models import PurchaseOrder, ReplenishmentProposal
from tests.helpers import audit_rows, count, outbox_types


def last_audit():
    return audit_rows()[-1]


# ----------------------------------------------------------------- read tools


def test_find_at_risk_orders(db, viewer):
    result = server.find_at_risk_orders()
    assert result["count"] == 5
    assert result["fully_allocatable"] == 4
    short = next(o for o in result["orders"] if not o["can_fully_allocate"])
    assert short["po_number"] == "PK-10005"
    assert last_audit().tool_or_endpoint == "mcp.find_at_risk_orders"
    assert last_audit().result == "OK"


def test_get_order_status_and_check_inventory(db, viewer):
    order = server.get_order_status("pk-10005")  # case-insensitive
    assert order["po_number"] == "PK-10005" and len(order["lines"]) == 2
    stock = server.check_inventory("TENT-2P-ULT")
    assert stock["below_reorder_point"] is True
    assert stock["total_available"] == 12


def test_list_low_stock_and_audit_log(db, viewer):
    assert server.list_low_stock()["count"] == 4
    log = server.get_audit_log(limit=5)
    assert log["entries"][0]["tool_or_endpoint"] == "mcp.list_low_stock"


# ----------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "call,message",
    [
        (lambda: server.check_inventory("NOT-REAL"), "Unknown SKU"),
        (lambda: server.get_order_status("PO-DOES-NOT-EXIST"), "No order found"),
        (lambda: server.find_at_risk_orders(days=99), "days must be"),
        (lambda: server.get_audit_log(limit=0), "limit must be"),
        (lambda: server.propose_replenishment("NOT-REAL", 10, "x"), "Unknown SKU"),
        (lambda: server.propose_replenishment("TENT-2P-ULT", 0, "x"), "greater than 0"),
        (lambda: server.propose_replenishment("TENT-2P-ULT", -5, "x"), "greater than 0"),
        (lambda: server.propose_replenishment("TENT-2P-ULT", 601, "x"), "limit is 10 x"),
        (lambda: server.allocate_order("PO-DOES-NOT-EXIST"), "No order found"),
    ],
)
def test_bad_arguments_are_rejected_and_audited(db, planner, call, message):
    with pytest.raises(ToolError, match=message):
        call()
    assert last_audit().result == "ERROR"
    assert count(ReplenishmentProposal) == 1  # only the seeded one; nothing was written


# ----------------------------------------------------------------- authorization


def test_viewer_cannot_use_write_tools(db, viewer):
    with pytest.raises(ToolError, match="ACCESS DENIED"):
        server.propose_replenishment("TENT-2P-ULT", 60, "Unblock PK-10005")
    with pytest.raises(ToolError, match="ACCESS DENIED"):
        server.allocate_order("SS-20007")
    denied = [r for r in audit_rows() if r.result == "DENIED"]
    assert [r.tool_or_endpoint for r in denied] == ["mcp.propose_replenishment", "mcp.allocate_order"]
    assert denied[0].actor == "test-viewer" and denied[0].role == "viewer"
    assert denied[0].arguments == {"sku": "TENT-2P-ULT", "qty": 60, "reason": "Unblock PK-10005"}
    assert outbox_types() == []


def test_unknown_role_is_denied_even_for_reads(db, monkeypatch):
    monkeypatch.setenv("MCP_ROLE", "admin")
    with pytest.raises(ToolError, match="not recognised"):
        server.list_low_stock()


def test_missing_role_defaults_to_read_only(db, monkeypatch):
    monkeypatch.delenv("MCP_ROLE", raising=False)
    server.list_low_stock()
    with pytest.raises(ToolError, match="ACCESS DENIED"):
        server.allocate_order("SS-20007")


# ----------------------------------------------------------------- write tools


def test_allocate_order_success_and_shortage(db, planner):
    ok = server.allocate_order("SS-20007")
    assert ok["allocated"] is True and ok["status"] == "ALLOCATED"
    short = server.allocate_order("PK-10005")
    assert short["allocated"] is False
    assert short["shortages"][0]["sku"] == "TENT-2P-ULT"
    assert server.get_order_status("PK-10005")["status"] == "ACKNOWLEDGED"  # nothing reserved
    with pytest.raises(ToolError, match="already allocated"):
        server.allocate_order("SS-20007")


def test_propose_creates_pending_and_never_a_purchase_order(db, planner):
    pos_before = count(PurchaseOrder)
    result = server.propose_replenishment("TENT-2P-ULT", 60, "Unblock PK-10005")
    assert result["status"] == "PENDING"
    assert result["proposed_by"] == "test-planner via MCP"
    assert count(PurchaseOrder) == pos_before
    assert outbox_types() == ["replenishment.proposed"]
    with pytest.raises(ToolError, match="already waiting"):
        server.propose_replenishment("TENT-2P-ULT", 60, "again")


def test_no_approval_tool_is_exposed():
    names = {t.name for t in asyncio.run(server.mcp.list_tools())}
    assert names == {
        "get_order_status", "check_inventory", "find_at_risk_orders", "list_low_stock",
        "get_audit_log", "propose_replenishment", "allocate_order",
    }  # fmt: skip
    assert not any("approv" in n or "purchase" in n for n in names)


def test_tool_descriptions_are_specific():
    for tool in asyncio.run(server.mcp.list_tools()):
        assert len(tool.description) > 120, tool.name
