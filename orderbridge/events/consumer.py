"""Reusable Redpanda/Kafka consumer used by scripts/watch_events.py and tests."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Iterator

from orderbridge.config import settings
from orderbridge.events.outbox import TOPICS


@dataclass
class ReceivedEvent:
    topic: str
    partition: int
    offset: int
    key: str | None
    payload: dict[str, Any]


def build_consumer(from_beginning: bool = False, group_id: str | None = None):
    from confluent_kafka import Consumer

    return Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            # A fresh group id each run means "just show me the stream", no shared offsets.
            "group.id": group_id or f"orderbridge-watch-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "earliest" if from_beginning else "latest",
            "enable.auto.commit": False,
        }
    )


def iter_events(
    topics: list[str] | None = None, from_beginning: bool = False, poll_timeout: float = 1.0
) -> Iterator[ReceivedEvent | None]:
    """Yield events forever. Yields None on each idle poll so callers can stop or tick."""
    consumer = build_consumer(from_beginning)
    consumer.subscribe(topics or TOPICS)
    try:
        while True:
            msg = consumer.poll(poll_timeout)
            if msg is None:
                yield None
                continue
            if msg.error():
                # Partition EOF and "unknown topic" (before first event) are normal at startup.
                yield None
                continue
            try:
                payload = json.loads(msg.value().decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                payload = {"raw": msg.value().decode("utf-8", errors="replace")}
            yield ReceivedEvent(
                topic=msg.topic(),
                partition=msg.partition(),
                offset=msg.offset(),
                key=msg.key().decode("utf-8") if msg.key() else None,
                payload=payload,
            )
    finally:
        consumer.close()
