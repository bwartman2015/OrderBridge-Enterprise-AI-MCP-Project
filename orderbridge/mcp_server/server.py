"""OrderBridge MCP server.

Every tool call goes through `_run_tool`, which applies the same three controls
an API gateway policy would:

  1. Authorization  - is this role allowed to use this kind of tool?
  2. Validation     - are the arguments real (SKU, PO) and sane (quantities)?
  3. Audit          - record who called what, with which arguments, and the result.

Tool docstrings are written for the AI: they are how it decides which tool to call.

IMPORTANT for stdio servers: never print() to stdout. stdout carries the MCP
protocol; logs go to stderr.
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated, Any, Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import Field
from sqlalchemy.orm import Session

from orderbridge.audit import recent_audit_entries, record_audit
from orderbridge.db import session_scope
from orderbridge.mcp_server.auth import READ, WRITE, current_identity, denial_message, is_allowed
from orderbridge.mcp_server.validation import (
    require_int_in_range,
    require_known_po,
    require_known_sku,
    require_reasonable_qty,
)
from orderbridge.services.errors import DomainError
from orderbridge.services.inventory import find_at_risk_orders as _find_at_risk_orders
from orderbridge.services.inventory import inventory_snapshot, list_low_stock as _list_low_stock
from orderbridge.services.orders import allocate_order as _allocate_order
from orderbridge.services.orders import order_to_dict
from orderbridge.services.replenishment import propose_replenishment as _propose
from orderbridge.services.replenishment import proposal_to_dict

log = logging.getLogger("orderbridge.mcp")

INSTRUCTIONS = """\
OrderBridge is a supply-chain order hub (a mock ERP) for an outdoor-gear distributor.
Trading partners: SWIFT (SwiftShip Logistics, 3PL), PEAK (Peak Outfitters, retailer),
GRANITE (Granite Manufacturing, contract manufacturer). Warehouses: WH-EAST, WH-WEST.

Guidance:
- Investigate with read tools before using write tools.
- allocate_order is all-or-nothing; if stock is short it reserves nothing and reports shortages.
- propose_replenishment only creates a PENDING proposal. A human approves it outside this
  assistant; never say a proposal is approved or that a purchase order exists until a human
  approves it.
- If a tool returns ACCESS DENIED, explain that to the user; do not try to work around it.
"""

mcp = FastMCP("orderbridge", instructions=INSTRUCTIONS)


def _run_tool(
    tool: str,
    arguments: dict[str, Any],
    permission: str,
    action: Callable[[Session], Any],
    summarize: Callable[[Any], str] | None = None,
) -> Any:
    """Authorize -> run (validation happens first inside `action`) -> audit."""
    identity = current_identity()
    endpoint = f"mcp.{tool}"

    if not is_allowed(identity, permission):
        message = denial_message(identity, tool, permission)
        record_audit(identity.actor, identity.role, endpoint, arguments, "DENIED", message)
        log.warning("DENIED %s for %s/%s", tool, identity.actor, identity.role)
        raise ToolError(message)

    try:
        with session_scope() as session:  # commits only if the whole action succeeds
            result = action(session)
    except DomainError as exc:  # validation or business-rule failure
        record_audit(identity.actor, identity.role, endpoint, arguments, "ERROR", str(exc))
        raise ToolError(str(exc)) from exc
    except Exception as exc:
        log.exception("Tool %s failed", tool)
        record_audit(
            identity.actor, identity.role, endpoint, arguments, "ERROR",
            f"Unexpected {type(exc).__name__}: {exc}",
        )
        raise ToolError(f"Internal error in {tool}; the details were logged.") from exc

    detail = summarize(result) if summarize else "OK"
    record_audit(identity.actor, identity.role, endpoint, arguments, "OK", detail)
    return result


# =============================================================================
# Read tools (viewer and planner)
# =============================================================================


@mcp.tool()
def get_order_status(
    po_number: Annotated[str, Field(description="Customer PO number exactly as sent, e.g. 'PK-10005'.")],
    partner_code: Annotated[
        str | None,
        Field(description="Optional: SWIFT, PEAK or GRANITE. Only needed if the PO number is ambiguous."),
    ] = None,
) -> dict[str, Any]:
    """Get the full status of ONE customer purchase order by its PO number.

    Returns the partner, status, requested ship date, every line (SKU, quantity,
    price), the warehouse allocations, and any shipments (carrier and tracking number).
    Status flow: RECEIVED -> ACKNOWLEDGED -> ALLOCATED -> SHIPPED (or CANCELLED).
    Use this for questions like "Where is PO PK-10005?" or "Has SS-20007 shipped?".
    """

    def action(session: Session) -> dict[str, Any]:
        return order_to_dict(require_known_po(session, po_number, partner_code))

    return _run_tool(
        "get_order_status",
        {"po_number": po_number, "partner_code": partner_code},
        READ,
        action,
        lambda r: f"{r['po_number']} is {r['status']}",
    )


@mcp.tool()
def check_inventory(
    sku: Annotated[str, Field(description="Product SKU, e.g. 'TENT-2P-ULT'.")],
) -> dict[str, Any]:
    """Check stock for ONE SKU: on hand, allocated and available, per warehouse and in total.

    available = on_hand - allocated (stock not yet promised to an order). Also returns
    the reorder point and quantity, supplier lead time, whether the SKU is below its
    reorder point, unallocated demand from open orders, pending replenishment
    proposals, and open purchase orders. Call once per SKU.
    """

    def action(session: Session) -> dict[str, Any]:
        product = require_known_sku(session, sku)
        return inventory_snapshot(session, product.sku)

    return _run_tool(
        "check_inventory",
        {"sku": sku},
        READ,
        action,
        lambda r: f"{r['sku']} available {r['total_available']}",
    )


@mcp.tool()
def find_at_risk_orders(
    days: Annotated[
        int, Field(description="Look-ahead window in days (0-30). Default 2 = due today through 2 days out.")
    ] = 2,
) -> dict[str, Any]:
    """Find customer orders at risk of missing their requested ship date, and explain why.

    An order is at risk when it is NOT yet allocated (status RECEIVED or ACKNOWLEDGED)
    and its requested ship date is within `days` days or already past. Each result
    lists its reasons, including any SKUs that are short on stock (needed vs available),
    and `can_fully_allocate`, which tells you whether allocate_order would succeed now.
    Start here for questions like "Which orders are at risk?".
    """

    def action(session: Session) -> dict[str, Any]:
        window = require_int_in_range("days", days, 0, 30)
        orders = _find_at_risk_orders(session, window)
        return {
            "days": window,
            "count": len(orders),
            "fully_allocatable": sum(1 for o in orders if o["can_fully_allocate"]),
            "orders": orders,
        }

    return _run_tool(
        "find_at_risk_orders", {"days": days}, READ, action, lambda r: f"{r['count']} at-risk order(s)"
    )


@mcp.tool()
def list_low_stock() -> dict[str, Any]:
    """List every SKU whose total available stock is at or below its reorder point.

    For each SKU: available, reorder point, standard reorder quantity, lead time,
    unallocated order demand, quantities already pending approval or on open purchase
    orders, and a suggested_order_qty. Check pending_replenishment_qty before proposing
    more, to avoid duplicate proposals.
    """

    def action(session: Session) -> dict[str, Any]:
        items = _list_low_stock(session)
        return {"count": len(items), "items": items}

    return _run_tool("list_low_stock", {}, READ, action, lambda r: f"{r['count']} low-stock SKU(s)")


@mcp.tool()
def get_audit_log(
    limit: Annotated[int, Field(description="How many recent entries to return (1-200). Default 20.")] = 20,
) -> dict[str, Any]:
    """Show the most recent audit trail entries, newest first.

    Every MCP tool call, REST write, EDI file and human approval is recorded with:
    actor, role, tool or endpoint, arguments, result (OK, DENIED or ERROR) and detail.
    Use this to show what the AI or users did, or to confirm a denied attempt was logged.
    """

    def action(session: Session) -> dict[str, Any]:
        count = require_int_in_range("limit", limit, 1, 200)
        entries = recent_audit_entries(session, count)
        return {"count": len(entries), "entries": entries}

    return _run_tool("get_audit_log", {"limit": limit}, READ, action, lambda r: f"{r['count']} entries")


# =============================================================================
# Write tools (planner only)
# =============================================================================


@mcp.tool()
def allocate_order(
    po_number: Annotated[str, Field(description="Customer PO number to allocate, e.g. 'SS-20007'.")],
    partner_code: Annotated[
        str | None, Field(description="Optional: SWIFT, PEAK or GRANITE, if the PO number is ambiguous.")
    ] = None,
) -> dict[str, Any]:
    """Reserve warehouse stock for every line of an order (WRITE - planner role only).

    All-or-nothing: if every line can be filled, stock is reserved, the order becomes
    ALLOCATED, and the allocations per warehouse are returned. If any SKU is short,
    NOTHING is reserved and the result lists the shortages (needed, available, short_by).
    Only RECEIVED or ACKNOWLEDGED orders can be allocated.
    """

    def action(session: Session) -> dict[str, Any]:
        order = require_known_po(session, po_number, partner_code)
        return _allocate_order(session, order).to_dict()

    return _run_tool(
        "allocate_order",
        {"po_number": po_number, "partner_code": partner_code},
        WRITE,
        action,
        lambda r: r["message"],
    )


@mcp.tool()
def propose_replenishment(
    sku: Annotated[str, Field(description="SKU to replenish, e.g. 'TENT-2P-ULT'.")],
    qty: Annotated[
        int, Field(description="Units to buy. Positive, and at most 10x the SKU's reorder_qty.")
    ],
    reason: Annotated[
        str,
        Field(description="Why this is needed, for the human approver (e.g. which orders it unblocks)."),
    ],
) -> dict[str, Any]:
    """Propose buying more stock for a SKU (WRITE - planner role only).

    Creates a replenishment proposal with status PENDING. It does NOT create a purchase
    order: a human must approve it with the approval CLI, outside this assistant.
    Only one pending proposal per SKU is allowed. Use list_low_stock or check_inventory
    first to pick a sensible quantity (suggested_order_qty is a good default).
    """

    def action(session: Session) -> dict[str, Any]:
        product = require_known_sku(session, sku)
        require_reasonable_qty(product, qty)
        identity = current_identity()
        proposal = _propose(session, product.sku, qty, reason, proposed_by=f"{identity.actor} via MCP")
        return {
            **proposal_to_dict(proposal),
            "next_step": (
                "PENDING human approval. A person must run scripts/approve.py; the AI cannot approve. "
                "No purchase order exists yet."
            ),
        }

    return _run_tool(
        "propose_replenishment",
        {"sku": sku, "qty": qty, "reason": reason},
        WRITE,
        action,
        lambda r: f"Proposal #{r['id']} PENDING for {r['qty']} x {r['sku']}",
    )


# NOTE: There is deliberately NO approve/reject tool. Approval is a human-only step
# (scripts/approve.py). This is segregation of duties: the AI can propose spending
# money but can never approve it, even with the planner role.


# =============================================================================
# Prompt (a reusable, guided workflow the user can pick in their MCP client)
# =============================================================================


@mcp.prompt()
def daily_risk_review() -> str:
    """Guided daily review: at-risk orders, stock checks, safe allocations, replenishment."""
    return (
        "Run the daily OrderBridge risk review:\n"
        "1. Call find_at_risk_orders and summarise each order and why it is at risk.\n"
        "2. For SKUs on those orders, call check_inventory.\n"
        "3. Allocate only the orders where can_fully_allocate is true, and report results.\n"
        "4. Call list_low_stock. For any SKU that blocks an at-risk order, call "
        "propose_replenishment with a clear reason. Skip SKUs that already have a pending proposal.\n"
        "5. Finish with a short table: order, action taken, and what still needs a human decision."
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, stream=sys.stderr, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    identity = current_identity()
    log.info("OrderBridge MCP server starting (actor=%s, role=%s)", identity.actor, identity.role)
    mcp.run()  # stdio transport by default


if __name__ == "__main__":
    main()
