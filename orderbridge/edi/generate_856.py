"""Build an 856 Advance Ship Notice (ASN) using a simple Shipment/Order/Item hierarchy.

  HL*1**S   shipment level: carrier (TD5), tracking (REF*CN), ship date (DTM*011), parties (N1)
  HL*2*1*O  order level:    customer PO number (PRF)
  HL*n*2*I  item level:     SKU (LIN) and quantity shipped (SN1), one per line
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from orderbridge.edi.x12 import build_interchange


@dataclass
class AsnLine:
    line_no: int
    sku: str
    qty: int


def build_856(
    sender_id: str,
    receiver_id: str,
    control_number: int,
    shipment_id: int,
    shipped_at: datetime,
    carrier: str,
    tracking_number: str,
    po_number: str,
    ship_to_name: str,
    ship_from_name: str,
    lines: list[AsnLine],
    usage_indicator: str = "T",
    when: datetime | None = None,
) -> str:
    when = when or datetime.now()
    body: list[list[str]] = [
        ["BSN", "00", f"SHP{shipment_id:06d}", shipped_at.strftime("%Y%m%d"), shipped_at.strftime("%H%M")],
        ["HL", "1", "", "S"],
        ["TD5", "", "2", carrier],
        ["REF", "CN", tracking_number],
        ["DTM", "011", shipped_at.strftime("%Y%m%d")],
        ["N1", "ST", ship_to_name],
        ["N1", "SF", ship_from_name],
        ["HL", "2", "1", "O"],
        ["PRF", po_number],
    ]
    hl = 2
    for line in lines:
        hl += 1
        body += [
            ["HL", str(hl), "2", "I"],
            ["LIN", str(line.line_no), "VP", line.sku],
            ["SN1", str(line.line_no), str(line.qty), "EA"],
        ]
    body.append(["CTT", str(hl)])  # number of HL segments
    return build_interchange(
        sender_id, receiver_id, control_number, "SH", "856", body, usage_indicator, when
    )
