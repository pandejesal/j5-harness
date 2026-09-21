"""Append-only JSONL ledger of decompose/dispatch/result/critique entries."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

ENTRY_TYPES: tuple[str, ...] = ("decompose", "dispatch", "result", "critique", "error", "blocked", "probe")


@dataclass
class LedgerEntry:
    seq: int
    ts: float
    entry_type: str
    task_id: str
    payload: dict

    def to_dict(self) -> dict:
        return {
            "seq": self.seq,
            "ts": self.ts,
            "type": self.entry_type,
            "task_id": self.task_id,
            "payload": self.payload,
        }


class DelegationLedger:
    """Append-only JSONL log. Each line is one LedgerEntry dict."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._seq = self._count_lines()

    def _count_lines(self) -> int:
        if not self.path.exists():
            return 0
        count = 0
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    count += 1
        return count

    def append(self, entry_type: str, task_id: str, payload: dict | None = None) -> LedgerEntry:
        if entry_type not in ENTRY_TYPES:
            raise ValueError(f"unknown entry_type {entry_type!r}; expected one of {list(ENTRY_TYPES)}")
        if not task_id:
            raise ValueError("task_id must be non-empty")
        entry = LedgerEntry(
            seq=self._seq + 1,
            ts=time.time(),
            entry_type=entry_type,
            task_id=task_id,
            payload=dict(payload or {}),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
        self._seq += 1
        return entry

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        out: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def entries_for(self, task_id: str) -> list[dict]:
        return [e for e in self.read_all() if e.get("task_id") == task_id]
