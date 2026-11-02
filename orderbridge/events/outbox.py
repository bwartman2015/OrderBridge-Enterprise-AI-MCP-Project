"""Write business events to the outbox table.

`add_event` only ADDS a row to the caller's session; it never commits. The row is
saved by the same COMMIT as the business change, so both happen or neither does.
Think of it as a guaranteed-delivery queue that lives inside the ERP database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from orderbridge.models import OutboxEvent

# The first part of the event type decides which Redpanda topic it goes to.
TOPIC_BY_PREFIX = {
    "order": "orders",
    "inventory": "inventory",
    "replenishment": "approvals",
    "purchase_order": "approvals",
}
TOPICS = sorted(set(TOPIC_BY_PREFIX.values()))


def topic_for(event_type: str) -> str:
    """Map e.g. 'order.shipped' -> 'orders'."""
    prefix = event_type.split(".", 1)[0]
    try:
        return TOPIC_BY_PREFIX[prefix]
    except KeyError as exc:
        raise ValueError(f"No topic configured for event type '{event_type}'") from exc


def add_event(session: Session, event_type: str, key: str, data: dict[str, Any]) -> OutboxEvent:
    """Stage an event in the outbox as part of the caller's current transaction.

    Args:
        event_type: dotted name, e.g. "order.received".
        key: Kafka message key (e.g. the PO number or SKU). Events with the same
             key land on the same partition, so they stay in order.
        data: JSON-serialisable event body.
    """
    topic_for(event_type)  # fail fast on an unknown event type
    payload = {
        "event_id": str(uuid.uuid4()),  # consumers can use this to de-duplicate
        "event_type": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "key": key,
        "data": data,
    }
    event = OutboxEvent(event_type=event_type, payload=payload, attempts=0)
    session.add(event)
    return event
