"""Speculative execution of independent paths: run multiple branches in parallel,
return first successful result, cancel others.

Stdlib-only: uses concurrent.futures with cancellation. Designed for
free-tier model routing where multiple models can be tried in parallel.
"""

from __future__ import annotations

import concurrent.futures
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, Any

T = TypeVar("T")


@dataclass(frozen=True)
class SpeculativeConfig:
    """Configuration for speculative execution."""

    max_branches: int = 4
    timeout_s: float = 30.0
    cancel_on_success: bool = True
    min_success_score: float = 0.0  # For scored branches


@dataclass(frozen=True)
class BranchResult:
    """Result from one speculative branch."""

    branch_id: str
    ok: bool
    value: Any | None = None
    error: str | None = None
    latency_ms: float = 0.0
    score: float | None = None


class SpeculativeExecutor:
    """Run multiple independent branches, return first success."""

    def __init__(self, config: SpeculativeConfig | None = None) -> None:
        self.config = config or SpeculativeConfig()
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._cancelled = False

    def __enter__(self) -> "SpeculativeExecutor":
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_branches,
            thread_name_prefix="speculative",
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown()

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def run_branches(
        self,
        branches: dict[str, Callable[[], T]],
        score_fn: Callable[[T], float] | None = None,
    ) -> BranchResult:
        """Execute all branches; return first that succeeds (and meets score)."""
        if self._executor is None:
            raise RuntimeError("executor not started; use 'with SpeculativeExecutor()'")

        futures: dict[concurrent.futures.Future[T], str] = {}
        for bid, fn in branches.items():
            futures[self._executor.submit(fn)] = bid

        start = time.perf_counter()
        deadline = start + self.config.timeout_s

        while futures:
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                break

            done, _ = concurrent.futures.wait(
                futures.keys(),
                timeout=min(remaining, 0.1),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )

            for fut in done:
                bid = futures.pop(fut)
                latency = (time.perf_counter() - start) * 1000.0
                try:
                    value = fut.result(timeout=0)
                    score = score_fn(value) if score_fn else None
                    if score is not None and score < self.config.min_success_score:
                        continue  # Treat as failure
                    result = BranchResult(
                        branch_id=bid, ok=True, value=value, latency_ms=latency, score=score
                    )
                    if self.config.cancel_on_success:
                        self._cancel_remaining(futures)
                    return result
                except Exception as exc:  # noqa: BLE001
                    # Branch failed; continue waiting for others
                    pass

        # All branches failed or timed out
        return BranchResult(
            branch_id="",
            ok=False,
            error="all branches failed or timed out",
            latency_ms=(time.perf_counter() - start) * 1000.0,
        )

    def _cancel_remaining(self, futures: dict[concurrent.futures.Future, str]) -> None:
        for fut in futures:
            fut.cancel()

    def run_with_fallback(
        self,
        primary: Callable[[], T],
        fallbacks: list[Callable[[], T]],
        score_fn: Callable[[T], float] | None = None,
    ) -> BranchResult:
        """Run primary first; on failure, speculate across fallbacks."""
        try:
            start = time.perf_counter()
            value = primary()
            latency = (time.perf_counter() - start) * 1000.0
            score = score_fn(value) if score_fn else None
            return BranchResult(
                branch_id="primary", ok=True, value=value, latency_ms=latency, score=score
            )
        except Exception:  # noqa: BLE001
            pass

        branches = {f"fallback_{i}": fb for i, fb in enumerate(fallbacks)}
        return self.run_branches(branches, score_fn)


def speculate(
    branches: dict[str, Callable[[], T]],
    max_branches: int = 4,
    timeout_s: float = 30.0,
    cancel_on_success: bool = True,
) -> BranchResult:
    """Convenience function for speculative execution."""
    config = SpeculativeConfig(
        max_branches=max_branches,
        timeout_s=timeout_s,
        cancel_on_success=cancel_on_success,
    )
    with SpeculativeExecutor(config) as exec:
        return exec.run_branches(branches)