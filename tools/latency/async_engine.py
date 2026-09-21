"""Async engine: unified async/await interface with sync fallback, rate limiting, and retries.

Stdlib-only: uses asyncio with thread-pool for blocking calls. Provides
semaphore-based concurrency control, exponential backoff retry, and
circuit breaker integration.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import random
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class AsyncConfig:
    """Configuration for the async engine."""

    max_concurrent: int = 10
    default_timeout_s: float = 30.0
    max_retries: int = 3
    base_backoff_s: float = 0.5
    max_backoff_s: float = 8.0
    jitter: float = 0.1


@dataclass
class CircuitBreaker:
    """Simple circuit breaker: trips after N failures in window."""

    failure_threshold: int = 5
    window_s: float = 60.0
    cooldown_s: float = 30.0
    _failures: list[float] = field(default_factory=list)
    _open_until: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def call(self, fn: Callable[..., Coroutine[Any, Any, T]], *args, **kwargs) -> T:
        async with self._lock:
            now = time.time()
            if now < self._open_until:
                raise RuntimeError(f"circuit open until {self._open_until:.0f}")
            # Prune old failures
            self._failures = [t for t in self._failures if now - t < self.window_s]

        try:
            result = await fn(*args, **kwargs)
            async with self._lock:
                self._failures.clear()
            return result
        except Exception:
            async with self._lock:
                self._failures.append(time.time())
                if len(self._failures) >= self.failure_threshold:
                    self._open_until = time.time() + self.cooldown_s
            raise

    def is_open(self) -> bool:
        return time.time() < self._open_until


class AsyncEngine:
    """Async task engine with semaphore, retries, and circuit breaker."""

    def __init__(self, config: AsyncConfig | None = None) -> None:
        self.config = config or AsyncConfig()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)
        self._thread_pool: concurrent.futures.ThreadPoolExecutor | None = None
        self._circuit_breakers: dict[str, CircuitBreaker] = {}

    async def __aenter__(self) -> "AsyncEngine":
        self._thread_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=self.config.max_concurrent,
            thread_name_prefix="async-engine",
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.shutdown()

    async def shutdown(self) -> None:
        if self._thread_pool is not None:
            self._thread_pool.shutdown(wait=True, cancel_futures=True)
            self._thread_pool = None

    def _get_breaker(self, key: str) -> CircuitBreaker:
        if key not in self._circuit_breakers:
            self._circuit_breakers[key] = CircuitBreaker()
        return self._circuit_breakers[key]

    async def run(
        self,
        coro: Coroutine[Any, Any, T],
        timeout_s: float | None = None,
        key: str | None = None,
    ) -> T:
        """Run a coroutine with semaphore, timeout, and optional circuit breaker."""
        timeout = timeout_s if timeout_s is not None else self.config.default_timeout_s
        async with self._semaphore:
            if key:
                breaker = self._get_breaker(key)
                return await asyncio.wait_for(breaker.call(lambda: coro), timeout=timeout)
            return await asyncio.wait_for(coro, timeout=timeout)

    async def run_with_retry(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, T]],
        timeout_s: float | None = None,
        key: str | None = None,
        retries: int | None = None,
    ) -> T:
        """Run with exponential backoff retry."""
        max_retries = retries if retries is not None else self.config.max_retries
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                return await self.run(coro_factory(), timeout_s, key)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt < max_retries:
                    backoff = min(
                        self.config.base_backoff_s * (2**attempt) + random.uniform(0, self.config.jitter),
                        self.config.max_backoff_s,
                    )
                    await asyncio.sleep(backoff)

        raise last_exc or RuntimeError("retry exhausted")

    async def run_in_thread(
        self,
        fn: Callable[..., T],
        *args,
        timeout_s: float | None = None,
        **kwargs,
    ) -> T:
        """Run a blocking function in thread pool with semaphore."""
        if self._thread_pool is None:
            raise RuntimeError("engine not started; use 'async with AsyncEngine()'")
        timeout = timeout_s if timeout_s is not None else self.config.default_timeout_s
        loop = asyncio.get_running_loop()
        async with self._semaphore:
            fut = loop.run_in_executor(self._thread_pool, lambda: fn(*args, **kwargs))
            return await asyncio.wait_for(fut, timeout=timeout)

    async def gather(
        self,
        *coros: Coroutine[Any, Any, T],
        timeout_s: float | None = None,
        return_exceptions: bool = False,
    ) -> list[T | BaseException]:
        """Gather multiple coroutines with shared semaphore."""
        async def _wrapped(coro: Coroutine[Any, Any, T]) -> T | BaseException:
            try:
                return await self.run(coro, timeout_s)
            except Exception as exc:
                if return_exceptions:
                    return exc
                raise

        return await asyncio.gather(*[_wrapped(c) for c in coros], return_exceptions=return_exceptions)

    def circuit_breaker_status(self) -> dict[str, bool]:
        return {k: v.is_open() for k, v in self._circuit_breakers.items()}


async def run_async(
    coro: Coroutine[Any, Any, T],
    max_concurrent: int = 10,
    timeout_s: float = 30.0,
) -> T:
    """Convenience function: run single coroutine with engine."""
    config = AsyncConfig(max_concurrent=max_concurrent, default_timeout_s=timeout_s)
    async with AsyncEngine(config) as engine:
        return await engine.run(coro)