"""Inbound 850 Purchase Order -> order in the mock ERP + outbound 855 acknowledgment.

Segments we read from each 850 transaction set:
  BEG  BEG03 = PO number, BEG05 = PO date (CCYYMMDD)
  DTM  DTM01 = 010 (requested ship date), DTM02 = the date
  N1   N101 = party qualifier (ST ship-to, BY buyer), N102 = name
  PO1  PO101 line no, PO102 qty, PO103 unit of measure, PO104 unit price,
       then qualifier/ID pairs from PO106 (VP vendor part, SK SKU, BP buyer part)
  CTT  CTT01 = number of PO1 lines (checked if present)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from orderbridge.config import settings
from orderbridge.edi.generate_855 import build_855
from orderbridge.edi.outbound import OutboundDocument, next_control_number
from orderbridge.edi.x12 import Interchange, TransactionSet, X12Error, parse_x12
from orderbridge.models import Partner, Product
from orderbridge.services.orders import (
    NewOrderLine,
    acknowledge_order,
    create_order,
    get_partner_by_isa_id,
)

PRODUCT_ID_QUALIFIERS = ("VP", "SK", "BP")  # in order of preference


@dataclass
class Line850:
    line_no: int
    qty: int
    uom: str
    unit_price: Decimal
    sku: str


@dataclass
class PurchaseOrder850:
    po_number: str
    po_date: date | None
    requested_ship_date: date | None
    parties: dict[str, str] = field(default_factory=dict)  # N101 -> N102
    lines: list[Line850] = field(default_factory=list)


@dataclass
class Result850:
    """What happened to one 850, for logging and the processed-file summary."""

    partner_code: str
    po_number: str
    order_id: int | None
    ack_type: str  # AD accepted, AC accepted with changes, RD rejected
    accepted_skus: list[str]
    rejected_skus: list[str]
    acknowledgment: OutboundDocument


def _parse_date(value: str, what: str) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except ValueError as exc:
        raise X12Error(f"{what} '{value}' is not a valid CCYYMMDD date.") from exc


def parse_850(tx: TransactionSet) -> PurchaseOrder850:
    """Pull the business data out of one 850 transaction set."""
    beg = tx.first("BEG")
    if beg is None or not beg.get(3):
        raise X12Error(f"850 transaction {tx.control_number} has no BEG segment with a PO number (BEG03).")
    po = PurchaseOrder850(
        po_number=beg.get(3).strip(),
        po_date=_parse_date(beg.get(5), "BEG05 PO date"),
        requested_ship_date=None,
    )
    for dtm in tx.find("DTM"):
        if dtm.get(1) == "010":
            po.requested_ship_date = _parse_date(dtm.get(2), "DTM02 requested ship date")
    for n1 in tx.find("N1"):
        po.parties[n1.get(1)] = n1.get(2)

    seen = set()
    for index, po1 in enumerate(tx.find("PO1"), start=1):
        line_no = int(po1.get(1)) if po1.get(1).isdigit() else index
        if line_no in seen:
            raise X12Error(f"PO {po.po_number}: PO1 line number {line_no} is used twice.")
        seen.add(line_no)
        try:
            qty_decimal = Decimal(po1.get(2))
            unit_price = Decimal(po1.get(4) or "0")
        except InvalidOperation as exc:
            raise X12Error(f"PO {po.po_number} line {line_no}: quantity or price is not a number.") from exc
        if qty_decimal <= 0 or qty_decimal != qty_decimal.to_integral_value():
            raise X12Error(f"PO {po.po_number} line {line_no}: quantity must be a positive whole number.")
        ids = {po1.get(p): po1.get(p + 1) for p in range(6, len(po1.elements), 2)}
        sku = next((ids[q] for q in PRODUCT_ID_QUALIFIERS if ids.get(q)), "")
        if not sku:
            raise X12Error(f"PO {po.po_number} line {line_no}: no product ID (VP, SK or BP) in PO1.")
        po.lines.append(
            Line850(line_no, int(qty_decimal), po1.get(3) or "EA", unit_price, sku.strip().upper())
        )
    if not po.lines:
        raise X12Error(f"PO {po.po_number} has no PO1 line items.")

    ctt = tx.first("CTT")
    if ctt is not None and ctt.get(1) and ctt.get(1) != str(len(po.lines)):
        raise X12Error(f"CTT01 says {ctt.get(1)} line items but PO {po.po_number} has {len(po.lines)}.")
    return po


def _handle_one(session: Session, partner: Partner, tx: TransactionSet) -> Result850:
    po = parse_850(tx)
    skus = {line.sku for line in po.lines}
    known = set(session.scalars(select(Product.sku).where(Product.sku.in_(skus))))
    accepted = [line for line in po.lines if line.sku in known]
    rejected = [line for line in po.lines if line.sku not in known]

    order_id = None
    if accepted:
        ack_type = "AC" if rejected else "AD"
        order = create_order(
            session,
            partner,
            po.po_number,
            po.requested_ship_date,
            [NewOrderLine(l.line_no, l.sku, l.qty, l.unit_price) for l in accepted],
            source="EDI-850",
        )
        acknowledge_order(session, order, ack_type, [l.sku for l in rejected])
        order_id = order.id
    else:
        ack_type = "RD"  # every line rejected: no order is created

    control = next_control_number(session)
    text = build_855(
        sender_id=settings.our_isa_id,
        receiver_id=partner.edi_isa_id,
        control_number=control,
        po=po,
        ack_type=ack_type,
        accepted_skus=known,
        usage_indicator=settings.edi_usage_indicator,
    )
    return Result850(
        partner_code=partner.code,
        po_number=po.po_number,
        order_id=order_id,
        ack_type=ack_type,
        accepted_skus=[l.sku for l in accepted],
        rejected_skus=[l.sku for l in rejected],
        acknowledgment=OutboundDocument(
            filename=f"855_{partner.code}_{po.po_number}_{control:09d}.edi", text=text
        ),
    )


def identify_partner(session: Session, interchange: Interchange) -> Partner:
    """The ISA sender ID tells us which trading partner sent the file."""
    if interchange.receiver_id != settings.our_isa_id:
        raise X12Error(
            f"Interchange is addressed to '{interchange.receiver_id}', not to us ('{settings.our_isa_id}')."
        )
    partner = get_partner_by_isa_id(session, interchange.sender_id)
    if partner is None:
        raise X12Error(f"Unknown trading partner: no partner has ISA ID '{interchange.sender_id}'.")
    return partner


def process_850_text(session: Session, text: str) -> list[Result850]:
    """Parse a whole file and create orders. All-or-nothing: the caller commits once."""
    interchange = parse_x12(text)
    partner = identify_partner(session, interchange)
    transactions = list(interchange.transactions())
    for tx in transactions:
        if tx.set_id != "850":
            raise X12Error(f"Only 850 purchase orders are accepted here; found a {tx.set_id}.")
    return [_handle_one(session, partner, tx) for tx in transactions]
