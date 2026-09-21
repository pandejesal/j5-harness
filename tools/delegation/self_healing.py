"""Self-healing: circuit breaker (structured errors) + cycle detection."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field


def structured_error(code: str, message: str, task_id: str | None = None,
                     retryable: bool = True, details: dict | None = None) -> dict:
    return {
        "code": code,
        "message": message,
        "task_id": task_id,
        "retryable": retryable,
        "details": dict(details or {}),
        "ts": time.time(),
    }


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    cooldown_s: float = 60.0
    _failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    _opened_at: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")

    def can_execute(self, key: str, now: float | None = None) -> bool:
        opened = self._opened_at.get(key)
        if opened is None:
            return True
        return (now if now is not None else time.time()) - opened >= self.cooldown_s

    def record_success(self, key: str) -> None:
        self._failures[key] = 0
        self._opened_at.pop(key, None)

    def record_failure(self, key: str, now: float | None = None) -> dict | None:
        self._failures[key] += 1
        if self._failures[key] >= self.failure_threshold:
            self._opened_at[key] = now if now is not None else time.time()
            return structured_error(
                "circuit-open",
                f"breaker open for {key!r} after {self._failures[key]} failures",
                retryable=False,
                details={"key": key, "failures": self._failures[key]},
            )
        return None

    def call(self, key: str, fn, *args, **kwargs) -> dict:
        """Execute fn or return a structured error if the breaker is open/fails."""
        if not self.can_execute(key):
            return {"ok": False, "error": structured_error(
                "circuit-open", f"breaker open for {key!r}; call blocked",
                retryable=False, details={"key": key})}
        try:
            return {"ok": True, "value": fn(*args, **kwargs)}
        except Exception as exc:  # noqa: BLE001 - structured, never raw
            opened = self.record_failure(key)
            return {"ok": False, "error": structured_error(
                "call-failed", str(exc), retryable=True,
                details={"key": key, "breaker_opened": opened is not None})}


class CycleDetector:
    """Block A->B->C->A delegation loops. Edges: task -> dependency."""

    def __init__(self) -> None:
        self._edges: dict[str, set[str]] = defaultdict(set)

    def add_edge(self, frm: str, to: str) -> None:
        self._edges[frm].add(to)
        self._edges.setdefault(to, set())

    def has_cycle(self) -> bool:
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(node: str) -> bool:
            if node in done:
                return False
            if node in visiting:
                return True
            visiting.add(node)
            for nxt in self._edges.get(node, ()):
                if visit(nxt):
                    return True
            visiting.discard(node)
            done.add(node)
            return False

        return any(visit(n) for n in list(self._edges))

    def check_path(self, path: list[str]) -> dict | None:
        """Return structured error if path revisits a node, else None."""
        seen: set[str] = set()
        for node in path:
            if node in seen:
                loop = path[path.index(node):] + [node]
                return structured_error(
                    "delegation-cycle", f"cycle blocked: {' -> '.join(loop)}",
                    retryable=False, details={"loop": loop})
            seen.add(node)
        return None
