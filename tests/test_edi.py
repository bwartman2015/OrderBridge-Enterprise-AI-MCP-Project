"""EDI inbound processing: folder watcher, 850 -> order, 855 out, error handling."""

import shutil

from sqlalchemy import select

from orderbridge.db import new_session
from orderbridge.edi.watcher import poll_once
from orderbridge.edi.x12 import parse_x12
from orderbridge.models import Order
from tests.conftest import SAMPLES
from tests.helpers import outbox_types


def drop(edi_dirs, name, as_name=None):
    shutil.copy(SAMPLES / name, edi_dirs / "inbound" / (as_name or name))


def order(po):
    with new_session() as s:
        o = s.scalar(select(Order).where(Order.po_number == po))
        if o:
            _ = o.lines  # load lines before the session closes
        return o


def test_valid_850_creates_order_and_855(db, edi_dirs):
    drop(edi_dirs, "850_valid_PEAK.edi")
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "PROCESSED", outcome.message

    o = order("PK-EDI-5001")
    assert o is not None and o.status == "ACKNOWLEDGED" and len(o.lines) == 3
    assert not list((edi_dirs / "inbound").iterdir())
    assert len(list((edi_dirs / "processed").iterdir())) == 1

    [ack] = list((edi_dirs / "outbound").glob("855_PEAK_PK-EDI-5001_*.edi"))
    tx = next(parse_x12(ack.read_text()).transactions())
    assert tx.first("BAK").get(2) == "AD"
    assert outbox_types() == ["order.received", "order.acknowledged"]


def test_unknown_sku_is_rejected_on_855_but_order_created(db, edi_dirs):
    drop(edi_dirs, "850_unknown_sku_SWIFT.edi")
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "PROCESSED"
    o = order("SS-EDI-7001")
    assert [l.sku for l in o.lines] == ["STOVE-CAN", "FAK-TRAIL"]  # CANOE-16FT dropped
    [ack] = list((edi_dirs / "outbound").glob("855_SWIFT_*.edi"))
    tx = next(parse_x12(ack.read_text()).transactions())
    assert tx.first("BAK").get(2) == "AC"
    assert [s.get(1) for s in tx.find("ACK")] == ["IA", "IR", "IA"]


def test_malformed_file_goes_to_error_with_reason(db, edi_dirs):
    drop(edi_dirs, "850_malformed_GRANITE.edi")
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "ERROR"
    errors = sorted((edi_dirs / "error").iterdir())
    assert len(errors) == 2  # the file and its .reason.txt
    reason = next(p for p in errors if p.name.endswith(".reason.txt")).read_text()
    assert "SE01" in reason
    assert order("GM-EDI-3001") is None
    assert not list((edi_dirs / "outbound").iterdir())
    assert outbox_types() == []


def test_duplicate_po_is_rejected(db, edi_dirs):
    drop(edi_dirs, "850_valid_PEAK.edi")
    poll_once(min_age_seconds=0)
    drop(edi_dirs, "850_valid_PEAK.edi", "again.edi")
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "ERROR"
    assert "Duplicate PO" in outcome.message


def test_unknown_partner_is_rejected(db, edi_dirs):
    text = (SAMPLES / "850_valid_PEAK.edi").read_text().replace("PEAKOUTFIT     ", "STRANGERCO     ")
    (edi_dirs / "inbound" / "stranger.edi").write_text(text)
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "ERROR"
    assert "Unknown trading partner" in outcome.message


def test_all_lines_unknown_sends_rd_and_no_order(db, edi_dirs):
    text = (SAMPLES / "850_valid_PEAK.edi").read_text()
    for sku in ("BOTTLE-1L", "PACK-DAY-22", "SOCK-MERINO"):
        text = text.replace(sku, "X-" + sku[:8])
    (edi_dirs / "inbound" / "allbad.edi").write_text(text)
    [outcome] = poll_once(min_age_seconds=0)
    assert outcome.status == "PROCESSED"
    assert order("PK-EDI-5001") is None
    [ack] = list((edi_dirs / "outbound").iterdir())
    assert next(parse_x12(ack.read_text()).transactions()).first("BAK").get(2) == "RD"
