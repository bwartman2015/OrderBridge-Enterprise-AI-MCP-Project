"""Outbox publisher: moves events from the outbox table to Redpanda.

Why this guarantees no lost events: the business change and its outbox row are
committed in ONE database transaction. If the broker is down, the row just waits
(published_at stays NULL) and is retried with exponential backoff. A row is only
marked published after the broker acknowledges it.

Delivery is "at least once": if the publisher crashes after the broker acks but
before the DB update commits, that event is sent again on restart. Every event
carries a unique event_id so consumers can ignore duplicates.

Run:  python -m orderbridge.events.publisher
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderbridge.config import settings
from orderbridge.db import session_scope
from orderbridge.events.outbox import TOPICS, topic_for
from orderbridge.models import OutboxEvent

log = logging.getLogger("orderbridge.publisher")

BACKOFF_BASE_SECONDS = 1
BACKOFF_MAX_SECONDS = 60
# Give up on one send after this long; librdkafka retries internally until then.
MESSAGE_TIMEOUT_MS = 10_000


class PublishError(Exception):
    """The broker did not confirm delivery."""


class ProducerLike(Protocol):
    """The two confluent_kafka.Producer methods we use (tests pass a fake)."""

    def produce(self, topic: str, key: bytes, value: bytes, on_delivery: Any) -> None: ...
    def flush(self, timeout: float) -> int: ...


@dataclass
class BatchResult:
    sent: int = 0
    failed: int = 0


def backoff_seconds(attempts: int) -> int:
    """1s, 2s, 4s, 8s ... capped at 60s."""
    return min(BACKOFF_BASE_SECONDS * 2 ** max(attempts - 1, 0), BACKOFF_MAX_SECONDS)


def build_producer(bootstrap_servers: str | None = None):
    from confluent_kafka import Producer

    return Producer(
        {
            "bootstrap.servers": bootstrap_servers or settings.kafka_bootstrap_servers,
            "enable.idempotence": True,  # broker drops duplicate retries of the same send
            "acks": "all",
            "message.timeout.ms": MESSAGE_TIMEOUT_MS,
        }
    )


def ensure_topics(bootstrap_servers: str | None = None) -> None:
    """Create the topics if they do not exist (docker compose also creates them)."""
    from confluent_kafka.admin import AdminClient, NewTopic

    admin = AdminClient({"bootstrap.servers": bootstrap_servers or settings.kafka_bootstrap_servers})
    futures = admin.create_topics([NewTopic(t, num_partitions=1, replication_factor=1) for t in TOPICS])
    for topic, future in futures.items():
        try:
            future.result(timeout=10)
            log.info("Created topic %s", topic)
        except Exception as exc:  # already exists, or broker not up yet
            if "TOPIC_ALREADY_EXISTS" not in str(exc):
                log.warning("Could not create topic %s: %s", topic, exc)


def deliver(producer: ProducerLike, event: OutboxEvent) -> None:
    """Send one event and wait for the broker's acknowledgment."""
    errors: list[Any] = []

    def on_delivery(err, _msg):
        if err is not None:
            errors.append(err)

    producer.produce(
        topic_for(event.event_type),
        key=str(event.payload.get("key", event.id)).encode("utf-8"),
        value=json.dumps(event.payload).encode("utf-8"),
        on_delivery=on_delivery,
    )
    remaining = producer.flush(MESSAGE_TIMEOUT_MS / 1000 + 5)
    if errors:
        raise PublishError(str(errors[0]))
    if remaining:
        raise PublishError("Timed out waiting for the broker to acknowledge the event.")


def publish_batch(session: Session, producer: ProducerLike, batch_size: int = 100) -> BatchResult:
    """Send unpublished events strictly in id order.

    If the oldest unsent event is still backing off, nothing behind it is sent either
    (head-of-line blocking), so consumers never see events out of order.
    """
    now = datetime.now(timezone.utc)
    events = session.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.published_at.is_(None))
        .order_by(OutboxEvent.id)
        .limit(batch_size)
        .with_for_update()  # one publisher at a time works this queue
    ).all()

    result = BatchResult()
    for event in events:
        if event.next_attempt_at is not None and event.next_attempt_at > now:
            break  # still in its backoff window; everything behind it waits too
        try:
            deliver(producer, event)
        except Exception as exc:
            event.attempts += 1
            event.last_error = str(exc)[:1000]
            delay = backoff_seconds(event.attempts)
            event.next_attempt_at = now + timedelta(seconds=delay)
            result.failed += 1
            log.warning(
                "Event %s (%s) failed, attempt %s; retrying in %ss: %s",
                event.id, event.event_type, event.attempts, delay, exc,
            )
            break  # later events wait, so consumers never see them out of order
        event.published_at = datetime.now(timezone.utc)
        event.last_error = None
        result.sent += 1
        log.info("Published #%s %s -> %s", event.id, event.event_type, topic_for(event.event_type))
    return result


def run_forever(poll_seconds: float | None = None) -> None:
    poll_seconds = poll_seconds or settings.publisher_poll_seconds
    log.info("Outbox publisher -> %s (Ctrl+C to stop)", settings.kafka_bootstrap_servers)
    ensure_topics()
    producer = build_producer()
    while True:
        try:
            with session_scope() as session:
                result = publish_batch(session, producer)
        except Exception:
            log.exception("Publisher loop error; retrying shortly")
            result = BatchResult()
        if result.sent == 0:
            time.sleep(poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish outbox events to Redpanda")
    parser.add_argument("--once", action="store_true", help="publish one batch and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        with session_scope() as session:
            result = publish_batch(session, build_producer())
        print(f"sent={result.sent} failed={result.failed}")
        return
    try:
        run_forever()
    except KeyboardInterrupt:
        log.info("Stopped.")


if __name__ == "__main__":
    main()
