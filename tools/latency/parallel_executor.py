"""Bounded parallel task executor with backpressure and ordered results.

Stdlib-only: uses concurrent.futures with configurable max workers,
queue depth, and timeout. Preserves submission order in results.
"""

from __future__ import annotations

import concurrent.futures
import queue
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True)
class ExecutorConfig:
    """Configuration for the parallel executor."""

    max_workers: int = 4
    max_queue_size: int = 64
    default_timeout_s: float = 30.0
    preserve_order: bool = True


@dataclass(frozen=True)
class TaskResult:
    """Result of a single task execution."""

    index: int
    ok: bool
    value: object | None = None
    error: str | None = None
    latency_ms: float = 0.0


class BoundedExecutor:
    """Thread-pool executor with bounded queue and backpressure.

    Submits tasks up to max_queue_size; blocks on submit when full.
    Results are yielded in submission order when preserve_order=True.
    """

    def __init__(self, config: ExecutorConfig | None = None) -> None:
        self.config = config or ExecutorConfig()
        self._executor: concurrent.futures.ThreadPoolExecutor | None = None
        self._submit_lock = threading.Lock()
        self._shutdown = False

    def __enter__(self) -> "BoundedExecutor":
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_workers,
            thread_name_prefix="latency-exec",
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.shutdown(wait=True)

    def shutdown(self, wait: bool = True) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None
        self._shutdown = True

    def submit(self, fn: Callable[..., R], *args, **kwargs) -> concurrent.futures.Future[R]:
        """Submit a task; blocks if queue is full."""
        if self._shutdown or self._executor is None:
            raise RuntimeError("executor is shutdown")
        with self._submit_lock:
            # Backpressure: wait for queue slot
            while self._executor._work_queue.qsize() >= self.config.max_queue_size:  # type: ignore[attr-defined]
                time.sleep(0.01)
            return self._executor.submit(fn, *args, **kwargs)

    def map_ordered(
        self,
        fn: Callable[[T], R],
        items: Iterable[T],
        timeout_s: float | None = None,
    ) -> Iterator[TaskResult]:
        """Map fn over items, yielding results in submission order."""
        if self._executor is None:
            raise RuntimeError("executor not started; use 'with BoundedExecutor()'")
        timeout = timeout_s if timeout_s is not None else self.config.default_timeout_s
        futures: list[concurrent.futures.Future[R]] = []
        for idx, item in enumerate(items):
            futures.append(self._executor.submit(fn, item))
        for idx, fut in enumerate(futures):
            start = time.perf_counter()
            try:
                value = fut.result(timeout=timeout)
                latency = (time.perf_counter() - start) * 1000.0
                yield TaskResult(index=idx, ok=True, value=value, latency_ms=latency)
            except concurrent.futures.TimeoutError:
                latency = (time.perf_counter() - start) * 1000.0
                yield TaskResult(index=idx, ok=False, error="timeout", latency_ms=latency)
            except Exception as exc:  # noqa: BLE001
                latency = (time.perf_counter() - start) * 1000.0
                yield TaskResult(index=idx, ok=False, error=str(exc), latency_ms=latency)

    def map_unordered(
        self,
        fn: Callable[[T], R],
        items: Iterable[T],
        timeout_s: float | None = None,
    ) -> Iterator[TaskResult]:
        """Map fn over items, yielding results as they complete."""
        if self._executor is None:
            raise RuntimeError("executor not started; use 'with BoundedExecutor()'")
        timeout = timeout_s if timeout_s is not None else self.config.default_timeout_s
        futures = {self._executor.submit(fn, item): idx for idx, item in enumerate(items)}
        while futures:
            done, _ = concurrent.futures.wait(
                futures.keys(),
                timeout=min(timeout, 0.1),
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            for fut in done:
                idx = futures.pop(fut)
                start = time.perf_counter()
                try:
                    value = fut.result(timeout=0)
                    latency = (time.perf_counter() - start) * 1000.0
                    yield TaskResult(index=idx, ok=True, value=value, latency_ms=latency)
                except Exception as exc:  # noqa: BLE001
                    latency = (time.perf_counter() - start) * 1000.0
                    yield TaskResult(index=idx, ok=False, error=str(exc), latency_ms=latency)


def run_parallel(
    fn: Callable[[T], R],
    items: list[T],
    max_workers: int = 4,
    timeout_s: float = 30.0,
    preserve_order: bool = True,
) -> list[TaskResult]:
    """Convenience function: run fn over items with bounded parallelism."""
    config = ExecutorConfig(max_workers=max_workers, default_timeout_s=timeout_s, preserve_order=preserve_order)
    with BoundedExecutor(config) as exec:
        if preserve_order:
            return list(exec.map_ordered(fn, items, timeout_s))
        return list(exec.map_unordered(fn, items, timeout_s))