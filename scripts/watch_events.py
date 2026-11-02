#!/usr/bin/env python
"""Live event viewer: prints every event from Redpanda in colour as it arrives.

Usage:
  python scripts/watch_events.py                   new events only
  python scripts/watch_events.py --from-beginning  replay everything first
  python scripts/watch_events.py --topics orders approvals
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

from orderbridge.config import settings
from orderbridge.events.consumer import iter_events
from orderbridge.events.outbox import TOPICS

COLOURS = {"orders": "\033[36m", "inventory": "\033[33m", "approvals": "\033[35m"}
BOLD, DIM, RESET = "\033[1m", "\033[2m", "\033[0m"
if not sys.stdout.isatty() or os.getenv("NO_COLOR"):
    COLOURS = {k: "" for k in COLOURS}
    BOLD = DIM = RESET = ""


def summarise(event_type: str, data: dict) -> str:
    """One readable line per event type."""
    if event_type.startswith("order."):
        extra = ""
        if event_type == "order.acknowledged":
            extra = f" 855={data.get('ack_type')}"
            if data.get("rejected_skus"):
                extra += f" rejected={','.join(data['rejected_skus'])}"
        elif event_type == "order.shipped":
            extra = f" {data.get('carrier')} {data.get('tracking_number')}"
        elif event_type == "order.received":
            extra = f" via {data.get('source')}, {len(data.get('lines', []))} line(s)"
        return f"PO {data.get('po_number')} ({data.get('partner_code')}) -> {data.get('status')}{extra}"
    if event_type == "inventory.changed":
        return (
            f"{data.get('sku')} @ {data.get('warehouse')}: on_hand={data.get('on_hand')} "
            f"allocated={data.get('allocated')} available={data.get('available')} ({data.get('reason')})"
        )
    if event_type.startswith("replenishment."):
        who = data.get("decided_by") or data.get("proposed_by")
        po = f" -> {data['purchase_order_number']}" if data.get("purchase_order_number") else ""
        return f"Proposal #{data.get('id')}: {data.get('qty')} x {data.get('sku')} [{data.get('status')}] by {who}{po}"
    if event_type == "purchase_order.created":
        return f"{data.get('po_number')}: {data.get('qty')} x {data.get('sku')} approved by {data.get('approved_by')}"
    return json.dumps(data)[:160]


def main() -> None:
    parser = argparse.ArgumentParser(description="Watch OrderBridge events live")
    parser.add_argument("--from-beginning", action="store_true")
    parser.add_argument("--topics", nargs="+", default=TOPICS, choices=TOPICS)
    args = parser.parse_args()
    print(f"{BOLD}Watching {', '.join(args.topics)} on {settings.kafka_bootstrap_servers}{RESET} (Ctrl+C to stop)")
    try:
        for event in iter_events(args.topics, args.from_beginning):
            if event is None:
                continue
            payload = event.payload
            event_type = payload.get("event_type", "?")
            colour = COLOURS.get(event.topic, "")
            try:  # event times are UTC; show them in local time
                when = datetime.fromisoformat(payload["occurred_at"]).astimezone().strftime("%H:%M:%S")
            except (KeyError, ValueError):
                when = datetime.now().strftime("%H:%M:%S")
            print(
                f"{DIM}{when}{RESET} {colour}{BOLD}{event.topic:<9}{RESET} "
                f"{colour}{event_type:<26}{RESET} {summarise(event_type, payload.get('data', {}))}",
                flush=True,
            )
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
