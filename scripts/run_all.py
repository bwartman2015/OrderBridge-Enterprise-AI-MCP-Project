#!/usr/bin/env python
"""Start the three OrderBridge app processes together, with labelled, coloured logs:

  api        FastAPI on http://localhost:8000 (docs at /docs, dashboard at /dashboard)
  edi        EDI folder watcher (edi/inbound -> orders + 855s)
  publisher  outbox -> Redpanda

Ctrl+C stops all three. (You can also run each one on its own; see README.)
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
PROCESSES = {
    "api": [PY, "-m", "uvicorn", "orderbridge.api.main:app", "--port", "8000"],
    "edi": [PY, "-m", "orderbridge.edi.watcher"],
    "publisher": [PY, "-m", "orderbridge.events.publisher"],
}
COLOURS = {"api": "\033[32m", "edi": "\033[34m", "publisher": "\033[35m"}
RESET = "\033[0m"


def pump(name: str, proc: subprocess.Popen) -> None:
    for line in proc.stdout:
        print(f"{COLOURS[name]}{name:>9} |{RESET} {line}", end="", flush=True)


def _stop_on_sigterm(signum, frame):
    raise KeyboardInterrupt  # treat `kill` like Ctrl+C so the children are cleaned up too


def main() -> None:
    signal.signal(signal.SIGTERM, _stop_on_sigterm)
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    procs = {}
    for name, cmd in PROCESSES.items():
        procs[name] = subprocess.Popen(
            cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        threading.Thread(target=pump, args=(name, procs[name]), daemon=True).start()
    print("OrderBridge running: API http://localhost:8000/docs  Dashboard http://localhost:8000/dashboard")
    try:
        while all(p.poll() is None for p in procs.values()):
            threading.Event().wait(0.5)
        dead = [n for n, p in procs.items() if p.poll() is not None]
        print(f"Process(es) exited: {', '.join(dead)}. Stopping the rest.")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        for p in procs.values():
            if p.poll() is None:
                p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()


if __name__ == "__main__":
    main()
