"""Free model router: pick model + endpoint per task type.

Skips quarantined models, applies round-robin tiebreak, and serializes
dispatch (1 in-flight by default — shared Zen free-tier key per IP bucket).
"""

from __future__ import annotations

import asyncio
import threading
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import asdict, dataclass

try:
    from tools.router.model_registry import validate_task_type
    from tools.router.health_probe import HealthTracker
    from tools.router.feedback_loop import FeedbackLoop
    from tools.router.fallback_chain import ChainEntry, FallbackChainBuilder
except ImportError:  # script-mode fallback
    from model_registry import validate_task_type  # type: ignore[no-redef]
    from health_probe import HealthTracker  # type: ignore[no-redef]
    from feedback_loop import FeedbackLoop  # type: ignore[no-redef]
    from fallback_chain import ChainEntry, FallbackChainBuilder  # type: ignore[no-redef]

TIE_EPSILON = 0.02


@dataclass
class RoutingDecision:
    model: str
    endpoint: str
    expected_latency_ms: float
    reason: str
    chain: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


class FreeModelRouter:
    """Task-type router over registry models with health + EMA awareness."""

    def __init__(
        self,
        tracker: HealthTracker | None = None,
        feedback: FeedbackLoop | None = None,
        chain_builder: FallbackChainBuilder | None = None,
        max_in_flight: int = 1,
    ) -> None:
        self.tracker = tracker or HealthTracker()
        self.feedback = feedback or FeedbackLoop()
        self.chains = chain_builder or FallbackChainBuilder(self.tracker)
        self.max_in_flight = max(1, max_in_flight)
        self._lock = threading.Lock()
        self._alock = asyncio.Lock()
        self._in_flight = 0
        self._tiebreak: dict[str, int] = defaultdict(int)

    @contextmanager
    def dispatch_slot(self):
        """Serialize dispatch: at most `max_in_flight` (default 1) held."""
        with self._lock:
            if self._in_flight >= self.max_in_flight:
                raise RuntimeError(
                    f"dispatch serialized: {self._in_flight} already in-flight "
                    f"(max {self.max_in_flight})"
                )
            self._in_flight += 1
        try:
            yield
        finally:
            with self._lock:
                self._in_flight -= 1

    def pick(self, task_type: str) -> RoutingDecision:
        """Pick best model for task_type; skips quarantined; round-robin ties."""
        task_type = validate_task_type(task_type)
        with self._lock:
            chain = self.chains.build_chain(task_type, scores=self.feedback.ema_map())
            if not chain:
                raise RuntimeError(f"no available model for task_type {task_type!r} "
                                   "(all quarantined / retry-after / quota-exhausted)")
            top_score = self._chain_score(task_type, chain[0])
            tied = [e for e in chain
                    if abs(self._chain_score(task_type, e) - top_score) <= TIE_EPSILON]
            idx = self._tiebreak[task_type] % len(tied)
            self._tiebreak[task_type] += 1
            chosen = tied[idx]
            verdict = RoutingDecision(
                model=chosen.model_id,
                endpoint=chosen.endpoint,
                expected_latency_ms=chosen.expected_latency_ms,
                reason=("round-robin tiebreak "
                        f"{idx + 1}/{len(tied)}; " if len(tied) > 1 else "") + chosen.reason,
                chain=[e.model_id for e in chain],
            )
            return verdict

    def _chain_score(self, task_type: str, entry: ChainEntry) -> float:
        # Reuse builder ordering signal: entries arrive sorted, so rank proxy
        # is position-independent score from EMA + latency.
        ema = self.feedback.get_ema(entry.model_id)
        return round(ema - min(entry.expected_latency_ms / 20000.0, 0.5) * 0.2, 4)

    async def apick(self, task_type: str) -> RoutingDecision:
        async with self._alock:
            return self.pick(task_type)

    def status(self) -> dict:
        with self._lock:
            in_flight = self._in_flight
        return {
            "max_in_flight": self.max_in_flight,
            "in_flight": in_flight,
            "quarantined": self.tracker.quarantined_models(),
            "health": self.tracker.snapshot(),
            "scores": self.feedback.all_scores(),
        }
