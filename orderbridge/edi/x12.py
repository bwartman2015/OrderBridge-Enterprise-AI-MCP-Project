"""A small, readable X12 parser and envelope builder (no third-party EDI library).

X12 refresher:
  * A file is an INTERCHANGE:      ISA ... IEA   (the envelope)
  * containing FUNCTIONAL GROUPS:  GS ... GE     (one per document type, e.g. PO)
  * containing TRANSACTION SETS:   ST ... SE     (one business document, e.g. one 850)
  * Segments end with '~' and elements are separated by '*'.
  * The ISA segment is FIXED WIDTH: always exactly 106 characters, including the
    segment terminator. That is how a parser discovers the separators.

Validation done here (envelope level):
  * ISA is exactly 106 characters and every ISA element has its fixed width
  * SE01 (segment count) matches the real number of segments from ST to SE
  * SE02 matches ST02, GE02 matches GS06, IEA02 matches ISA13 (control numbers)
  * GE01 (number of transactions) and IEA01 (number of groups) are correct
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterator

ISA_LENGTH = 106
# Widths of ISA01..ISA16, in order.
ISA_ELEMENT_WIDTHS = [2, 10, 2, 10, 2, 15, 2, 15, 6, 4, 1, 5, 9, 1, 1, 1]


class X12Error(Exception):
    """The file is not valid X12. The message explains what is wrong, for the error folder."""


@dataclass
class Segment:
    """One segment. elements[0] is the segment ID, so get(3) is e.g. BEG03 (X12 numbering)."""

    elements: list[str]

    @property
    def id(self) -> str:
        return self.elements[0]

    def get(self, position: int, default: str = "") -> str:
        """Element by its X12 position number; missing trailing elements return `default`."""
        if position < len(self.elements):
            return self.elements[position]
        return default

    def __str__(self) -> str:
        return "*".join(self.elements)


@dataclass
class TransactionSet:
    """One business document (ST ... SE). `segments` excludes ST and SE."""

    set_id: str  # ST01, e.g. "850"
    control_number: str  # ST02
    segments: list[Segment] = field(default_factory=list)

    def find(self, segment_id: str) -> list[Segment]:
        return [s for s in self.segments if s.id == segment_id]

    def first(self, segment_id: str) -> Segment | None:
        found = self.find(segment_id)
        return found[0] if found else None


@dataclass
class FunctionalGroup:
    functional_id: str  # GS01, e.g. "PO" for 850s
    sender: str  # GS02
    receiver: str  # GS03
    control_number: str  # GS06
    version: str  # GS08
    transactions: list[TransactionSet] = field(default_factory=list)


@dataclass
class Interchange:
    sender_id: str  # ISA06 (trimmed)
    receiver_id: str  # ISA08 (trimmed)
    control_number: str  # ISA13
    usage_indicator: str  # ISA15: P = production, T = test
    element_separator: str
    segment_terminator: str
    groups: list[FunctionalGroup] = field(default_factory=list)

    def transactions(self) -> Iterator[TransactionSet]:
        for group in self.groups:
            yield from group.transactions


def _same_control_number(a: str, b: str) -> bool:
    """Control numbers match if equal as numbers (000000001 == 1) or as text."""
    a, b = a.strip(), b.strip()
    try:
        return int(a) == int(b)
    except ValueError:
        return a == b


def _as_int(value: str, what: str) -> int:
    try:
        return int(value.strip())
    except ValueError as exc:
        raise X12Error(f"{what} must be a number, got '{value}'.") from exc


def _read_isa(text: str) -> tuple[list[str], str, str]:
    """Validate the fixed-width ISA. Returns (ISA elements, element sep, segment terminator)."""
    if not text.startswith("ISA"):
        raise X12Error("File does not start with an ISA segment, so it is not an X12 interchange.")
    element_sep = text[3]
    # ISA16 is the single character after the 16th element separator; the segment
    # terminator follows it. Find them without assuming the widths are correct.
    positions = [i for i, ch in enumerate(text[:200]) if ch == element_sep]
    if len(positions) < 16 or positions[15] + 2 >= len(text):
        raise X12Error("ISA segment is incomplete: it must contain 16 elements.")
    isa16_index = positions[15] + 1
    segment_term = text[isa16_index + 1]
    isa_text = text[: isa16_index + 1]
    elements = isa_text.split(element_sep)

    problems = []
    for number, (value, width) in enumerate(zip(elements[1:], ISA_ELEMENT_WIDTHS), start=1):
        if len(value) != width:
            problems.append(f"ISA{number:02d} must be {width} characters but is {len(value)} ('{value}')")
    actual_length = len(isa_text) + 1  # + terminator
    if actual_length != ISA_LENGTH or problems:
        detail = "; ".join(problems) if problems else "element widths are wrong"
        raise X12Error(
            f"ISA segment must be exactly {ISA_LENGTH} characters (fixed width) but is "
            f"{actual_length}: {detail}."
        )
    if segment_term.isalnum() or segment_term == element_sep:
        raise X12Error(f"Invalid segment terminator '{segment_term}' after ISA16.")
    return elements, element_sep, segment_term


def parse_x12(text: str) -> Interchange:
    """Parse and validate an X12 interchange. Raises X12Error with a clear reason."""
    text = text.lstrip("﻿ \t\r\n")  # tolerate a byte-order mark or leading blank lines
    if not text:
        raise X12Error("File is empty.")
    isa_elements, element_sep, segment_term = _read_isa(text)

    raw_segments = [s.strip("\r\n \t") for s in text.split(segment_term)]
    segments = [Segment(s.split(element_sep)) for s in raw_segments if s]
    interchange = Interchange(
        sender_id=isa_elements[6].strip(),
        receiver_id=isa_elements[8].strip(),
        control_number=isa_elements[13],
        usage_indicator=isa_elements[15],
        element_separator=element_sep,
        segment_terminator=segment_term,
    )

    i = 1  # segments[0] is the ISA
    n = len(segments)

    def expect(segment_id: str, context: str) -> Segment:
        if i >= n:
            raise X12Error(f"Missing {segment_id} segment {context}.")
        if segments[i].id != segment_id:
            raise X12Error(f"Expected {segment_id} {context} but found '{segments[i].id}'.")
        return segments[i]

    while i < n and segments[i].id == "GS":
        gs = segments[i]
        group = FunctionalGroup(
            functional_id=gs.get(1),
            sender=gs.get(2),
            receiver=gs.get(3),
            control_number=gs.get(6),
            version=gs.get(8),
        )
        i += 1
        while i < n and segments[i].id == "ST":
            st = segments[i]
            tx = TransactionSet(set_id=st.get(1), control_number=st.get(2))
            i += 1
            while i < n and segments[i].id != "SE":
                if segments[i].id in ("ST", "GE", "GS", "IEA"):
                    raise X12Error(f"Transaction set {tx.control_number} is missing its SE trailer.")
                tx.segments.append(segments[i])
                i += 1
            se = expect("SE", f"to close transaction set {tx.control_number}")
            i += 1
            actual = len(tx.segments) + 2  # body + ST + SE
            declared = _as_int(se.get(1), "SE01 segment count")
            if declared != actual:
                raise X12Error(
                    f"SE01 says transaction set {tx.control_number} has {declared} segments, "
                    f"but it actually has {actual} (counting ST through SE)."
                )
            if not _same_control_number(se.get(2), tx.control_number):
                raise X12Error(
                    f"SE02 control number '{se.get(2)}' does not match ST02 '{tx.control_number}'."
                )
            group.transactions.append(tx)
        ge = expect("GE", f"to close functional group {group.control_number}")
        i += 1
        if _as_int(ge.get(1), "GE01") != len(group.transactions):
            raise X12Error(
                f"GE01 says {ge.get(1)} transaction set(s) but group {group.control_number} "
                f"contains {len(group.transactions)}."
            )
        if not _same_control_number(ge.get(2), group.control_number):
            raise X12Error(
                f"GE02 control number '{ge.get(2)}' does not match GS06 '{group.control_number}'."
            )
        interchange.groups.append(group)

    if not interchange.groups:
        raise X12Error("Interchange contains no GS functional group.")
    iea = expect("IEA", "to close the interchange")
    i += 1
    if _as_int(iea.get(1), "IEA01") != len(interchange.groups):
        raise X12Error(
            f"IEA01 says {iea.get(1)} group(s) but the interchange contains {len(interchange.groups)}."
        )
    if not _same_control_number(iea.get(2), interchange.control_number):
        raise X12Error(
            f"IEA02 control number '{iea.get(2)}' does not match ISA13 '{interchange.control_number}'."
        )
    if i < n:
        raise X12Error(f"Unexpected segment '{segments[i].id}' after IEA.")
    return interchange


def build_interchange(
    sender_id: str,
    receiver_id: str,
    control_number: int,
    functional_id: str,
    transaction_set_id: str,
    body: list[list[str]],
    usage_indicator: str = "T",
    when: datetime | None = None,
) -> str:
    """Wrap one transaction set's body segments in ST/SE, GS/GE and ISA/IEA envelopes.

    `body` is a list of segments, each a list of elements, e.g. [["BAK", "00", "AD", ...]].
    Output has one segment per line for readability (newlines are ignored by parsers).
    """
    if len(sender_id) > 15 or len(receiver_id) > 15:
        raise ValueError("ISA sender/receiver IDs can be at most 15 characters.")
    when = when or datetime.now()
    control9 = f"{control_number:09d}"
    isa = [
        "ISA", "00", " " * 10, "00", " " * 10,
        "ZZ", sender_id.ljust(15), "ZZ", receiver_id.ljust(15),
        when.strftime("%y%m%d"), when.strftime("%H%M"),
        "U", "00401", control9, "0", usage_indicator, ">",
    ]  # fmt: skip
    gs = ["GS", functional_id, sender_id, receiver_id, when.strftime("%Y%m%d"),
          when.strftime("%H%M"), str(control_number), "X", "004010"]  # fmt: skip
    st = ["ST", transaction_set_id, "0001"]
    se = ["SE", str(len(body) + 2), "0001"]
    ge = ["GE", "1", str(control_number)]
    iea = ["IEA", "1", control9]
    segments = [isa, gs, st, *body, se, ge, iea]
    return "\n".join("*".join(seg) + "~" for seg in segments) + "\n"
