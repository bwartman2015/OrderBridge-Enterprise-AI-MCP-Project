"""X12 parser and generator tests (no database needed)."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from orderbridge.edi.generate_855 import build_855
from orderbridge.edi.generate_856 import AsnLine, build_856
from orderbridge.edi.handler_850 import Line850, PurchaseOrder850, parse_850
from orderbridge.edi.x12 import X12Error, build_interchange, parse_x12
from tests.conftest import SAMPLES

VALID = (SAMPLES / "850_valid_PEAK.edi").read_text()


def test_parses_valid_850_envelope():
    ic = parse_x12(VALID)
    assert ic.sender_id == "PEAKOUTFIT"
    assert ic.receiver_id == "ORDERBRIDGE"
    assert ic.element_separator == "*" and ic.segment_terminator == "~"
    [tx] = list(ic.transactions())
    assert tx.set_id == "850"
    assert tx.first("BEG").get(3) == "PK-EDI-5001"


def test_parse_850_business_fields():
    po = parse_850(next(parse_x12(VALID).transactions()))
    assert po.po_number == "PK-EDI-5001"
    assert po.po_date == date(2026, 11, 2)
    assert po.requested_ship_date == date(2027, 12, 15)
    assert po.parties["ST"] == "Peak Outfitters DC Denver"
    assert [(l.sku, l.qty) for l in po.lines] == [("BOTTLE-1L", 24), ("PACK-DAY-22", 12), ("SOCK-MERINO", 36)]
    assert po.lines[0].unit_price == Decimal("28.80")


def test_isa_must_be_fixed_width():
    short_sender = VALID.replace("PEAKOUTFIT     ", "PEAKOUTFIT    ", 1)  # ISA06 now 14 chars
    with pytest.raises(X12Error, match=r"exactly 106 characters.*ISA06 must be 15"):
        parse_x12(short_sender)


def test_se_segment_count_must_match():
    with pytest.raises(X12Error, match="SE01 says transaction set 0001 has 12 segments"):
        parse_x12((SAMPLES / "850_malformed_GRANITE.edi").read_text())


def test_se02_must_match_st02():
    with pytest.raises(X12Error, match="SE02"):
        parse_x12(VALID.replace("SE*10*0001~", "SE*10*0002~"))


def test_ge_control_number_must_match_gs():
    with pytest.raises(X12Error, match="GE02"):
        parse_x12(VALID.replace("GE*1*5001~", "GE*1*5002~"))


def test_ge_transaction_count_must_match():
    with pytest.raises(X12Error, match="GE01"):
        parse_x12(VALID.replace("GE*1*5001~", "GE*2*5001~"))


def test_iea_control_number_must_match_isa():
    with pytest.raises(X12Error, match="IEA02"):
        parse_x12(VALID.replace("IEA*1*000005001~", "IEA*1*000005009~"))


def test_rejects_non_x12_and_empty():
    with pytest.raises(X12Error, match="ISA"):
        parse_x12("hello world")
    with pytest.raises(X12Error, match="empty"):
        parse_x12("   \n")


def test_missing_se_is_reported():
    broken = VALID.replace("SE*10*0001~\n", "")
    with pytest.raises(X12Error, match="missing its SE"):
        parse_x12(broken)


def test_single_line_file_without_newlines_parses():
    assert parse_x12(VALID.replace("\n", "")).control_number == "000005001"


def test_build_interchange_round_trips():
    text = build_interchange("ORDERBRIDGE", "PEAKOUTFIT", 1234, "PR", "855", [["BAK", "00", "AD", "PO1"]])
    ic = parse_x12(text)
    assert ic.control_number == "000001234"
    assert text.splitlines()[0].__len__() == 106


def _po():
    return PurchaseOrder850(
        po_number="PO-1",
        po_date=date(2026, 11, 1),
        requested_ship_date=date(2026, 11, 20),
        lines=[
            Line850(1, 5, "EA", Decimal("10.00"), "BOTTLE-1L"),
            Line850(2, 3, "EA", Decimal("99.00"), "NOPE-123"),
        ],
    )


def test_855_marks_lines_accepted_and_rejected():
    text = build_855("ORDERBRIDGE", "PEAKOUTFIT", 77, _po(), "AC", {"BOTTLE-1L"})
    tx = next(parse_x12(text).transactions())
    assert tx.set_id == "855"
    assert tx.first("BAK").get(2) == "AC"
    acks = [s.get(1) for s in tx.find("ACK")]
    assert acks == ["IA", "IR"]


def test_856_has_shipment_order_item_hierarchy():
    text = build_856(
        "ORDERBRIDGE", "PEAKOUTFIT", 78, 5, datetime(2026, 11, 2, 14, 0), "UPS", "1Z123",
        "PO-1", "Peak Outfitters", "OrderBridge", [AsnLine(1, "BOTTLE-1L", 5), AsnLine(2, "LAMP-HEAD", 2)],
    )  # fmt: skip
    tx = next(parse_x12(text).transactions())
    assert tx.set_id == "856"
    assert [s.get(3) for s in tx.find("HL")] == ["S", "O", "I", "I"]
    assert tx.first("REF").get(2) == "1Z123"
    assert tx.first("PRF").get(1) == "PO-1"
