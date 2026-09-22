#!/usr/bin/env python3
"""
Kilo Reply Watcher — polls Kilo inbox + InterHarness for kilo-to-* receipts.
Single-run mode (--once) or watch mode (--watch, polls every 30s).
Handles partial writes via .tmp+rename detection.
Logs to InterHarness/_tracker/kilo.log
"""

import sys
import json
import time
import os
import re
import hashlib
from pathlib import Path
from datetime import datetime, timezone

# Load config to get kilo paths
def load_config():
    config_path = Path(__file__).resolve().parent.parent / "reliability" / "reliability.config.json"
    with config_path.open("r", encoding="utf-8") as f:
        return json.load(f)

_config = load_config()
_kilo_cfg = _config.get("kilo", {})
ROOT = Path(_kilo_cfg.get("interharness", r"C:\Users\DELL\Documents\Default Project")).parent
KILO_INBOX = Path(_kilo_cfg.get("inbox", ROOT / "04-Prompt-Queues" / "Ecosystem" / "Kilo"))
INTERHARNESS = Path(_kilo_cfg.get("interharness", ROOT / "04-Prompt-Queues" / "Ecosystem" / "InterHarness"))
TRACKER_DIR = INTERHARNESS / "_tracker"
PENDING_FILE = TRACKER_DIR / "pending.jsonl"
LOG_FILE = TRACKER_DIR / "kilo.log"

def _ensure_tracker_dir() -> Path:
    """Create the tracker dir on first actual write — never at import.

    Importing this module (e.g. via `j5 --help`) must not touch the
    filesystem. Writers call this first.
    """
    TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    return TRACKER_DIR

# Strict frontmatter regex: only matches --- block at start of file
_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_ID_RE = re.compile(r"^id:\s*(.+)$", re.MULTILINE)


def log(msg):
    _ensure_tracker_dir()
    ts = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def stable_file(path, wait=0.5, max_wait=5.0):
    if not path.exists():
        return False
    last_size = -1
    start = time.time()
    while time.time() - start < max_wait:
        try:
            size = path.stat().st_size
            if size == last_size and size > 0:
                return True
            last_size = size
            time.sleep(wait)
        except OSError:
            time.sleep(wait)
    return path.stat().st_size > 0


def load_pending():
    pending = {}
    if PENDING_FILE.exists():
        with open(PENDING_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    entry = json.loads(line)
                    pending[entry["probe_id"]] = entry
                except json.JSONDecodeError:
                    pass
    return pending


def save_pending(pending):
    _ensure_tracker_dir()
    with open(PENDING_FILE, "w", encoding="utf-8") as f:
        f.write("# InterHarness v2 - Pending Tracker (JSONL)\n")
        f.write("# Format: one JSON object per line, append-only\n")
        f.write("# Fields: probe_id, sent_ts, deadline_ts, owner, reply_path, evidence_required\n")
        f.write("# Stale sweeper runs every 15min: if now > deadline_ts + 30min grace -> BLOCKED-stale receipt\n")
        for entry in pending.values():
            f.write(json.dumps(entry) + "\n")


def _extract_probe_id(content: str, fallback: str) -> str:
    """Extract probe_id from frontmatter block only."""
    m = _FM_RE.match(content)
    if m:
        fm = m.group(1)
        id_match = _ID_RE.search(fm)
        if id_match:
            return id_match.group(1).strip()
    return fallback


def scan_kilo_inbox():
    """Return list of task files in Kilo inbox (only files matching *-to-kilo-*.md pattern)."""
    tasks = []
    if KILO_INBOX.exists():
        for f in KILO_INBOX.glob("*-to-kilo-*.md"):
            if f.name.startswith("."):
                continue
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    content = fp.read()
                probe_id = _extract_probe_id(content, f.name)
                tasks.append({"file": f, "probe_id": probe_id, "type": "task"})
            except Exception as e:
                log(f"Error reading {f}: {e}")
    return tasks


def scan_interharness_receipts():
    receipts = []
    if INTERHARNESS.exists():
        for f in INTERHARNESS.glob("kilo-to-*.md"):
            if f.name.startswith("."):
                continue
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    content = fp.read()
                probe_id = _extract_probe_id(content, f.name)
                receipts.append({"file": f, "probe_id": probe_id, "type": "receipt"})
            except Exception as e:
                log(f"Error reading {f}: {e}")
    return receipts


def close_pending(pending, probe_id, reason="DONE"):
    if probe_id in pending:
        entry = pending.pop(probe_id)
        log(f"Closed probe {probe_id} ({reason})")
    return pending


def stale_sweep(pending):
    now = datetime.now(timezone.utc).timestamp()
    to_remove = []
    for pid, entry in pending.items():
        deadline = entry.get("deadline_ts")
        if deadline:
            try:
                dt = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
                deadline_ts = dt.timestamp()
            except (ValueError, TypeError):
                continue
            if now > deadline_ts + 1800:
                log(f"STALE: {pid} past deadline + 30min grace")
                to_remove.append(pid)
    for pid in to_remove:
        pending.pop(pid, None)
    return pending


def process_once():
    log("=== Watch cycle start ===")
    pending = load_pending()

    tasks = scan_kilo_inbox()
    for t in tasks:
        pid = t["probe_id"]
        if pid not in pending:
            deadline = datetime.now(timezone.utc).timestamp() + 3600
            pending[pid] = {
                "probe_id": pid,
                "sent_ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "deadline_ts": datetime.fromtimestamp(datetime.now(timezone.utc).timestamp() + 3600, tz=timezone.utc).isoformat().replace("+00:00", "Z"),
                "owner": "kilo",
                "reply_path": f"InterHarness/{Path(t['file']).stem.replace('hermes-to-kilo-', 'kilo-to-hermes-')}.md",
                "evidence_required": True
            }
            log(f"Registered new inbound task: {pid}")

    receipts = scan_interharness_receipts()
    for r in receipts:
        pid = r["probe_id"]
        if pid in pending:
            pending = close_pending(pending, pid, "RECEIPT")
            log(f"Closed {pid} via receipt")

    pending = stale_sweep(pending)
    save_pending(pending)
    log(f"=== Cycle complete, pending={len(pending)} ===")


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Run single cycle and exit")
    parser.add_argument("--watch", action="store_true", help="Continuous watch (poll every 30s)")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval seconds")
    args = parser.parse_args()

    if not args.once and not args.watch:
        parser.print_help()
        return 1

    log(f"Kilo watcher started (once={args.once}, watch={args.watch})")

    if args.once:
        process_once()
        return 0

    while True:
        try:
            process_once()
        except Exception as e:
            log(f"ERROR in cycle: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())