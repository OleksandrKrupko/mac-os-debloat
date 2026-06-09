#!/usr/bin/env python3
"""debloat-watcher: continuously kill respawned daemons we've marked disabled.

Reads list of labels from /etc/debloat-killlist.txt.
Every TICK seconds, finds running processes matching any label, sends SIGKILL.
Logs kills with timestamp to /var/log/debloat-watcher.log.

Runs as root via /Library/LaunchDaemons/ai.debloat.watcher.plist.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

KILLLIST_FILE = Path("/etc/debloat-killlist.txt")
LOG_FILE = Path("/var/log/debloat-watcher.log")
TICK = float(os.environ.get("DEBLOAT_TICK", "1.0"))

_running = True


def log(msg: str) -> None:
    line = f"{datetime.utcnow().isoformat(timespec='seconds')}Z  {msg}\n"
    try:
        with LOG_FILE.open("a") as f:
            f.write(line)
    except Exception:
        sys.stderr.write(line)


def load_labels() -> list[str]:
    if not KILLLIST_FILE.exists():
        return []
    out = []
    for line in KILLLIST_FILE.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def find_pids(labels: list[str]) -> dict[str, list[int]]:
    if not labels:
        return {}
    short_to_label = {l.rsplit(".", 1)[-1]: l for l in labels}
    label_set = set(labels)
    r = subprocess.run(
        ["ps", "-axm", "-o", "pid=,comm="],
        capture_output=True, text=True, check=False,
    )
    hits: dict[str, list[int]] = {}
    for line in r.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        cmd = parts[1]
        short = cmd.rsplit("/", 1)[-1]
        if short in short_to_label:
            hits.setdefault(short_to_label[short], []).append(pid)
            continue
        for lab in label_set:
            if lab in cmd:
                hits.setdefault(lab, []).append(pid)
                break
    return hits


def handle_sigterm(signum, frame):
    global _running
    _running = False
    log("received signal, shutting down")


def main() -> int:
    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)
    log(f"watcher started (tick={TICK}s, killlist={KILLLIST_FILE})")
    while _running:
        labels = load_labels()
        hits = find_pids(labels)
        for label, pids in hits.items():
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGKILL)
                    log(f"killed {label} pid={pid}")
                except (ProcessLookupError, PermissionError) as e:
                    log(f"kill failed {label} pid={pid}: {e}")
        time.sleep(TICK)
    log("watcher stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
