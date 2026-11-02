#!/usr/bin/env python
"""Human approval CLI for replenishment proposals.

The AI (through MCP) can only PROPOSE. A person approves or rejects here, and the
approver's name is recorded. Approving creates a purchase order and emits events.

Usage:
  python scripts/approve.py                        interactive: walk through pending proposals
  python scripts/approve.py --list                 show pending proposals and exit
  python scripts/approve.py --approve 3 --as brad  approve proposal #3 non-interactively
  python scripts/approve.py --reject 4 --as brad --note "Overstocked next month"
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys

from orderbridge.audit import record_audit
from orderbridge.db import session_scope
from orderbridge.services.errors import DomainError
from orderbridge.services.inventory import inventory_snapshot
from orderbridge.services.replenishment import decide_proposal, list_proposals, proposal_to_dict

BOLD, DIM, GREEN, RED, YELLOW, RESET = "\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[33m", "\033[0m"
if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    BOLD = DIM = GREEN = RED = YELLOW = RESET = ""


def pending() -> list[dict]:
    with session_scope() as session:
        rows = []
        for p in list_proposals(session, "PENDING"):
            stock = inventory_snapshot(session, p.sku)
            rows.append(
                {
                    **proposal_to_dict(p),
                    "description": p.product.description,
                    "unit_cost": float(p.product.unit_cost),
                    "available": stock["total_available"],
                    "reorder_point": stock["reorder_point"],
                }
            )
        return rows


def show(rows: list[dict]) -> None:
    if not rows:
        print(f"{GREEN}No pending proposals.{RESET}")
        return
    print(f"{BOLD}{len(rows)} pending proposal(s){RESET}")
    for r in rows:
        cost = r["qty"] * r["unit_cost"]
        print(
            f"\n{BOLD}#{r['id']}{RESET}  {r['sku']} ({r['description']})\n"
            f"   qty {r['qty']}  x ${r['unit_cost']:.2f} = {BOLD}${cost:,.2f}{RESET}\n"
            f"   available now {r['available']}, reorder point {r['reorder_point']}\n"
            f"   proposed by {r['proposed_by']} at {r['created_at'][:19]}\n"
            f"   reason: {r['reason']}"
        )


def decide(proposal_id: int, approve: bool, approver: str, note: str | None) -> bool:
    action = "approve" if approve else "reject"
    args = {"proposal_id": proposal_id, "decision": action, "note": note}
    try:
        with session_scope() as session:
            proposal, po = decide_proposal(session, proposal_id, approve, approver, note)
            po_number = po.po_number if po else None
    except DomainError as exc:
        record_audit(approver, "approver", "approve.py", args, "ERROR", str(exc))
        print(f"{RED}Could not {action} #{proposal_id}: {exc}{RESET}")
        return False
    if approve:
        detail = f"Approved proposal #{proposal_id}; created purchase order {po_number}"
        print(f"{GREEN}✔ {detail}{RESET}")
    else:
        detail = f"Rejected proposal #{proposal_id}"
        print(f"{YELLOW}✘ {detail}{RESET}")
    record_audit(approver, "approver", "approve.py", args, "OK", detail)
    return True


def ask_name(given: str | None) -> str:
    name = (given or os.getenv("APPROVER_NAME") or "").strip()
    while not name:
        default = getpass.getuser()
        name = input(f"Your name, recorded as the approver [{default}]: ").strip() or default
    return name


def interactive(approver: str | None) -> None:
    rows = pending()
    show(rows)
    if not rows:
        return
    name = ask_name(approver)
    for r in rows:
        while True:
            choice = input(f"\n#{r['id']} {r['sku']} x {r['qty']}: [a]pprove, [r]eject, [s]kip, [q]uit? ").strip().lower()
            if choice in ("a", "r", "s", "q"):
                break
        if choice == "q":
            break
        if choice == "s":
            continue
        note = input("Optional note: ").strip() or None
        decide(r["id"], choice == "a", name, note)


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve or reject replenishment proposals (humans only).")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true", help="list pending proposals and exit")
    group.add_argument("--approve", type=int, metavar="ID", help="approve this proposal id")
    group.add_argument("--reject", type=int, metavar="ID", help="reject this proposal id")
    parser.add_argument("--as", dest="approver", help="your name (recorded as the approver)")
    parser.add_argument("--note", help="optional decision note")
    args = parser.parse_args()

    if args.list:
        show(pending())
    elif args.approve is not None or args.reject is not None:
        ok = decide(args.approve or args.reject, args.approve is not None, ask_name(args.approver), args.note)
        sys.exit(0 if ok else 1)
    else:
        interactive(args.approver)


if __name__ == "__main__":
    main()
