"""Real broker round trip. Skipped automatically when Redpanda is not running."""

import json
import socket
import uuid

import pytest

from orderbridge.config import settings
from orderbridge.db import session_scope
from orderbridge.events.publisher import build_producer, ensure_topics, publish_batch
from orderbridge.services.orders import allocate_order, find_order_by_po


def _broker_up() -> bool:
    host, port = settings.kafka_bootstrap_servers.split(",")[0].rsplit(":", 1)
    try:
        with socket.create_connection((host, int(port)), timeout=2):
            return True
    except OSError:
        return False


@pytest.mark.skipif(not _broker_up(), reason="Redpanda not running (docker compose up -d)")
def test_outbox_events_reach_redpanda(db):
    from confluent_kafka import Consumer

    ensure_topics()
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_bootstrap_servers,
            "group.id": f"test-{uuid.uuid4().hex[:8]}",
            "auto.offset.reset": "latest",
        }
    )
    consumer.subscribe(["orders"])
    for _ in range(20):  # wait for partition assignment so we only see new messages
        consumer.poll(0.5)
        if consumer.assignment():
            break

    with session_scope() as s:
        allocate_order(s, find_order_by_po(s, "SS-20007"))
    with session_scope() as s:
        assert publish_batch(s, build_producer()).sent == 3

    seen = []
    for _ in range(40):
        msg = consumer.poll(0.5)
        if msg is not None and not msg.error():
            seen.append(json.loads(msg.value()))
            if any(e["event_type"] == "order.allocated" for e in seen):
                break
    consumer.close()
    assert any(e["event_type"] == "order.allocated" and e["key"] == "SS-20007" for e in seen)
