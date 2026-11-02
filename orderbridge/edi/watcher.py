"""EDI folder watcher (polling), like a Boomi Disk connector listener.

  edi/inbound/    drop 850 files here
  edi/processed/  successfully processed files (timestamp-prefixed)
  edi/error/      files that cannot be processed, each with a .reason.txt next to it
  edi/outbound/   855 acknowledgments we generate

Permanent errors (bad X12, duplicate PO, unknown partner) go to the error folder.
Transient errors (database down) leave the file in inbound so the next poll retries it.

Run:  python -m orderbridge.edi.watcher          (keeps polling)
      python -m orderbridge.edi.watcher --once   (process what is there, then exit)
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import OperationalError

from orderbridge.audit import record_audit
from orderbridge.config import settings
from orderbridge.db import session_scope
from orderbridge.edi.handler_850 import process_850_text
from orderbridge.edi.outbound import write_outbound
from orderbridge.edi.x12 import X12Error
from orderbridge.services.errors import DomainError

log = logging.getLogger("orderbridge.edi")


@dataclass
class FileOutcome:
    name: str
    status: str  # PROCESSED, ERROR, RETRY
    message: str
    moved_to: Path | None = None


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _move(path: Path, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{_stamp()}_{path.name}"
    shutil.move(str(path), target)
    return target


def process_file(path: Path) -> FileOutcome:
    """Process one inbound file end to end."""
    try:
        text = path.read_text(encoding="utf-8")
        with session_scope() as session:  # one transaction for the whole file
            results = process_850_text(session, text)
    except (X12Error, DomainError, UnicodeDecodeError) as exc:
        reason = f"{type(exc).__name__}: {exc}"
        moved = _move(path, settings.edi_error)
        moved.with_name(moved.name + ".reason.txt").write_text(
            f"File: {path.name}\nRejected at: {datetime.now().isoformat(timespec='seconds')}\n"
            f"Reason: {exc}\n",
            encoding="utf-8",
        )
        record_audit("edi-watcher", "system", "edi.850", {"file": path.name}, "ERROR", str(exc))
        log.warning("REJECTED %s -> error/ (%s)", path.name, exc)
        return FileOutcome(path.name, "ERROR", reason, moved)
    except OperationalError as exc:
        log.error("Database unavailable; will retry %s on the next poll (%s)", path.name, exc.orig)
        return FileOutcome(path.name, "RETRY", "database unavailable")

    # The database commit succeeded, so now it is safe to send the 855s.
    summaries = []
    for result in results:
        ack_path = write_outbound(result.acknowledgment)
        summaries.append(
            f"PO {result.po_number} from {result.partner_code}: 855 {result.ack_type} -> {ack_path.name}"
            + (f" (rejected SKUs: {', '.join(result.rejected_skus)})" if result.rejected_skus else "")
        )
        record_audit(
            "edi-watcher",
            "system",
            "edi.850",
            {"file": path.name, "po_number": result.po_number, "partner": result.partner_code},
            "OK",
            f"Order {result.order_id or '-'} created; 855 {result.ack_type}",
        )
    moved = _move(path, settings.edi_processed)
    for line in summaries:
        log.info("PROCESSED %s", line)
    return FileOutcome(path.name, "PROCESSED", "; ".join(summaries), moved)


def poll_once(min_age_seconds: float = 1.0) -> list[FileOutcome]:
    """Process every file in the inbound folder that has finished being written."""
    inbound = settings.edi_inbound
    inbound.mkdir(parents=True, exist_ok=True)
    outcomes = []
    now = time.time()
    for path in sorted(inbound.iterdir()):
        if path.is_dir() or path.name.startswith("."):
            continue
        if now - path.stat().st_mtime < min_age_seconds:
            continue  # probably still being copied in; pick it up next time
        outcomes.append(process_file(path))
    return outcomes


def run_forever() -> None:
    log.info("Watching %s every %ss (Ctrl+C to stop)", settings.edi_inbound, settings.edi_poll_seconds)
    while True:
        poll_once()
        time.sleep(settings.edi_poll_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description="Process EDI 850 files from edi/inbound/")
    parser.add_argument("--once", action="store_true", help="process current files and exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.once:
        for outcome in poll_once(min_age_seconds=0):
            print(f"{outcome.status:9} {outcome.name}: {outcome.message}")
    else:
        try:
            run_forever()
        except KeyboardInterrupt:
            log.info("Stopped.")


if __name__ == "__main__":
    main()
