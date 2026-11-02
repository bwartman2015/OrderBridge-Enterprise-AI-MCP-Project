"""Transactional outbox and publisher tests (a fake producer stands in for Redpanda)."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from orderbridge.db import new_session, session_scope
from orderbridge.events.publisher import backoff_seconds, publish_batch
from orderbridge.models import OutboxEvent
from orderbridge.services.orders import allocate_order, find_order_by_po
from tests.helpers import outbox_types


class FakeProducer:
    """Mimics confluent_kafka.Producer: calls on_delivery during flush()."""

    def __init__(self, fail=False):
        self.fail = fail
        self.sent = []
        self._pending = []

    def produce(self, topic, key, value, on_delivery):
        self._pending.append((topic, key, value, on_delivery))

    def flush(self, timeout):
        for topic, key, value, cb in self._pending:
            if self.fail:
                cb("Broker transport failure", None)
            else:
                self.sent.append((topic, key.decode(), value))
                cb(None, None)
        self._pending = []
        return 0


def test_state_change_and_event_commit_together(session):
    order = find_order_by_po(session, "SS-20007")
    allocate_order(session, order)
    session.commit()
    types = outbox_types()
    assert types[-1] == "order.allocated"
    assert types.count("inventory.changed") == 2  # STOVE-CAN and POT-TI-750


def test_rollback_leaves_no_event(session):
    order = find_order_by_po(session, "SS-20007")
    allocate_order(session, order)
    session.rollback()  # the business change failed -> its event must not exist either
    assert outbox_types() == []
    assert find_order_by_po(session, "SS-20007").status == "RECEIVED"


def _make_events(n=3):
    with session_scope() as s:
        allocate_order(s, find_order_by_po(s, "SS-20007"))  # creates 3 events
    return n


def test_publisher_sends_and_marks_published(db):
    _make_events()
    producer = FakeProducer()
    with session_scope() as s:
        result = publish_batch(s, producer)
    assert result.sent == 3 and result.failed == 0
    assert [t for t, _, _ in producer.sent] == ["inventory", "inventory", "orders"]
    assert producer.sent[-1][1] == "SS-20007"  # message key = PO number
    with new_session() as s:
        assert all(e.published_at for e in s.scalars(select(OutboxEvent)))


def test_publisher_failure_increments_attempts_and_backs_off(db):
    _make_events()
    with session_scope() as s:
        result = publish_batch(s, FakeProducer(fail=True))
    assert result.sent == 0 and result.failed == 1
    with new_session() as s:
        events = list(s.scalars(select(OutboxEvent).order_by(OutboxEvent.id)))
    first = events[0]
    assert first.attempts == 1 and first.published_at is None
    assert "Broker transport failure" in first.last_error
    assert first.next_attempt_at > datetime.now(timezone.utc)
    # Later events were not attempted, so ordering is preserved.
    assert all(e.attempts == 0 for e in events[1:])

    # While backing off, the publisher waits instead of hammering the broker...
    with session_scope() as s:
        assert publish_batch(s, FakeProducer()).sent == 0
    # ...and once the backoff has passed, everything is delivered in order.
    with session_scope() as s:
        for e in s.scalars(select(OutboxEvent)):
            e.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with session_scope() as s:
        assert publish_batch(s, FakeProducer()).sent == 3


@pytest.mark.parametrize("attempts,expected", [(1, 1), (2, 2), (3, 4), (4, 8), (7, 60), (20, 60)])
def test_exponential_backoff(attempts, expected):
    assert backoff_seconds(attempts) == expected
