"""Outbound EDI helpers: control numbers, the 856 for a shipment, and writing files."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from orderbridge.config import settings
from orderbridge.edi.generate_856 import AsnLine, build_856
from orderbridge.models import Order, Shipment


@dataclass
class OutboundDocument:
    """An EDI document ready to be written to edi/outbound/ once the DB commit succeeds."""

    filename: str
    text: str


def next_control_number(session: Session) -> int:
    """Next interchange/group control number from a database sequence (never reused)."""
    return int(session.scalar(text("SELECT nextval('edi_control_number_seq')")))


def build_856_document(session: Session, order: Order, shipment: Shipment) -> OutboundDocument:
    """Create the 856 ASN text for a shipment that was just recorded."""
    control = next_control_number(session)
    shipped_qty: dict[int, int] = {}
    for alloc in order.allocations:
        shipped_qty[alloc.line_no] = shipped_qty.get(alloc.line_no, 0) + alloc.qty
    lines = [
        AsnLine(line.line_no, line.sku, shipped_qty.get(line.line_no, line.qty)) for line in order.lines
    ]
    text_ = build_856(
        sender_id=settings.our_isa_id,
        receiver_id=order.partner.edi_isa_id,
        control_number=control,
        shipment_id=shipment.id,
        shipped_at=shipment.shipped_at.astimezone(),  # local time on the ASN
        carrier=shipment.carrier,
        tracking_number=shipment.tracking_number,
        po_number=order.po_number,
        ship_to_name=order.partner.name,
        ship_from_name="OrderBridge Distribution",
        lines=lines,
        usage_indicator=settings.edi_usage_indicator,
    )
    return OutboundDocument(f"856_{order.partner.code}_{order.po_number}_{control:09d}.edi", text_)


def write_outbound(doc: OutboundDocument, folder: Path | None = None) -> Path:
    """Write atomically (temp file + rename) so a partner never picks up half a file."""
    folder = folder or settings.edi_outbound
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / doc.filename
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".edi")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(doc.text)
    os.replace(tmp, target)
    return target
