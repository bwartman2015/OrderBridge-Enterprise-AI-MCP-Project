"""Build an 855 Purchase Order Acknowledgment.

BAK02 acknowledgment type:  AD = accepted as sent, AC = accepted with changes
(some lines rejected), RD = rejected. Each line gets an ACK segment:
ACK01 = IA (item accepted) or IR (item rejected, e.g. unknown SKU).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Iterable

from orderbridge.edi.x12 import build_interchange

if TYPE_CHECKING:
    from orderbridge.edi.handler_850 import PurchaseOrder850


def build_855(
    sender_id: str,
    receiver_id: str,
    control_number: int,
    po: "PurchaseOrder850",
    ack_type: str,
    accepted_skus: Iterable[str],
    usage_indicator: str = "T",
    when: datetime | None = None,
) -> str:
    when = when or datetime.now()
    accepted_skus = set(accepted_skus)
    po_date = po.po_date.strftime("%Y%m%d") if po.po_date else ""
    body: list[list[str]] = [
        # BAK01 00 = original; BAK09 = acknowledgment date
        ["BAK", "00", ack_type, po.po_number, po_date, "", "", "", "", when.strftime("%Y%m%d")],
    ]
    for line in po.lines:
        body.append(
            ["PO1", str(line.line_no), str(line.qty), line.uom, f"{line.unit_price:.2f}", "", "VP", line.sku]
        )
        status = "IA" if line.sku in accepted_skus else "IR"
        ack = ["ACK", status, str(line.qty), line.uom]
        if status == "IA" and po.requested_ship_date:
            ack += ["068", po.requested_ship_date.strftime("%Y%m%d")]  # 068 = current schedule ship
        body.append(ack)
    body.append(["CTT", str(len(po.lines))])
    return build_interchange(
        sender_id, receiver_id, control_number, "PR", "855", body, usage_indicator, when
    )
