"""Per-task-type fallback chains: Retry-After, daily quota, health reorder, endpoints."""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import asdict, dataclass

try:
    from tools.router.model_registry import (
        ZEN_ENDPOINTS, affinity, get_model, models_for_task, validate_task_type,
    )
    from tools.router.health_probe import HealthTracker
except ImportError:  # script-mode fallback
    from model_registry import (  # type: ignore[no-redef]
        ZEN_ENDPOINTS, affinity, get_model, models_for_task, validate_task_type,
    )
    from health_probe import HealthTracker  # type: ignore[no-redef]


@dataclass
class ChainEntry:
    model_id: str
    endpoint: str
    reason: str
    expected_latency_ms: float

    def to_dict(self) -> dict:
        return asdict(self)


class FallbackChainBuilder:
    """Builds ordered, endpoint-aware fallback chains from registry + health."""

    def __init__(
        self,
        tracker: HealthTracker | None = None,
        endpoints: tuple[str, ...] | list[str] | None = None,
    ) -> None:
        self.tracker = tracker or HealthTracker()
        self.endpoints = tuple(endpoints) if endpoints else tuple(ZEN_ENDPOINTS)
        # Daily quota window: UTC-day string -> {model_id: dispatch count}.
        self._daily_usage: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    @staticmethod
    def _today_key(now: float | None = None) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(now))

    def record_dispatch(self, model_id: str) -> None:
        self._daily_usage[self._today_key()][model_id] += 1

    def daily_used(self, model_id: str) -> int:
        return self._daily_usage[self._today_key()].get(model_id, 0)

    def quota_exhausted(self, model_id: str) -> bool:
        return self.daily_used(model_id) >= get_model(model_id).requests_per_day

    def endpoint_for(self, model_id: str, rank: int = 0) -> str:
        if not self.endpoints:
            raise ValueError("no endpoints configured")
        return self.endpoints[(abs(hash(model_id)) + rank) % len(self.endpoints)]

    def build_chain(
        self,
        task_type: str,
        scores: dict[str, float] | None = None,
        include_unavailable: bool = False,
    ) -> list[ChainEntry]:
        """Order candidates: available first, then by health/affinity/EMA.

        Honors Retry-After + daily quota window; dynamic reorder uses live
        health data (error rate, avg latency) and optional EMA quality scores.
        """
        task_type = validate_task_type(task_type)
        now = time.time()
        snapshot = self.tracker.snapshot()
        entries: list[tuple[tuple, ChainEntry]] = []

        for rank0, info in enumerate(models_for_task(task_type)):
            h = snapshot[info.model_id]
            quarantined = h["quarantined"]
            in_retry = self.tracker.in_retry_after(info.model_id, now)
            exhausted = self.quota_exhausted(info.model_id)
            available = not (quarantined or in_retry or exhausted)

            avg_lat = h["avg_latency_ms"] if h["avg_latency_ms"] is not None else float(info.expected_latency_ms)
            ema = (scores or {}).get(info.model_id, 0.5)
            # Higher is better: affinity + registry weight + EMA minus health penalties.
            rank_score = (
                affinity(task_type, info.model_id) * 0.4
                + info.weight * 0.2
                + ema * 0.3
                - h["error_rate"] * 0.5
                - min(avg_lat / 20000.0, 0.5) * 0.2
            )
            if not available:
                reason = ("quarantined" if quarantined
                          else "retry-after" if in_retry else "quota-exhausted")
            else:
                reason = (f"affinity={affinity(task_type, info.model_id):.2f} "
                          f"err={h['error_rate']:.2f} ema={ema:.2f}")
            entry = ChainEntry(
                model_id=info.model_id,
                endpoint=self.endpoint_for(info.model_id, rank0),
                reason=reason,
                expected_latency_ms=round(avg_lat, 1),
            )
            entries.append(((0 if available else 1, -rank_score), entry))

        entries.sort(key=lambda t: t[0])
        chain = [e for _, e in entries]
        if not include_unavailable:
            chain = [e for e in chain
                     if not e.reason.startswith(("quarantined", "retry-after", "quota-exhausted"))]
        # Reassign endpoints by final rank so failover spreads across endpoints.
        for i, e in enumerate(chain):
            e.endpoint = self.endpoints[i % len(self.endpoints)] if self.endpoints else e.endpoint
        return chain

    def next_available(
        self,
        task_type: str,
        scores: dict[str, float] | None = None,
    ) -> ChainEntry | None:
        chain = self.build_chain(task_type, scores)
        return chain[0] if chain else None
