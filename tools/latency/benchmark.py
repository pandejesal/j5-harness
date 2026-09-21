"""Benchmark suite: p50/p95/p99 latency, throughput, error rate reporting.

Stdlib-only: uses time.perf_counter for high-resolution timing.
Generates JSON output for CI integration.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class BenchmarkConfig:
    """Configuration for a benchmark run."""

    iterations: int = 100
    warmup: int = 5
    timeout_s: float = 30.0
    concurrency: int = 1
    percentiles: tuple[float, ...] = (50.0, 95.0, 99.0)


@dataclass(frozen=True)
class BenchmarkResult:
    """Results of a benchmark run."""

    name: str
    iterations: int
    successful: int
    failed: int
    error_rate: float
    latency_ms: dict[str, float]  # percentile -> value
    throughput_per_s: float
    min_ms: float
    max_ms: float
    mean_ms: float
    stdev_ms: float
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


def percentile(data: list[float], p: float) -> float:
    """Calculate percentile (nearest-rank method)."""
    if not data:
        return 0.0
    sorted_data = sorted(data)
    k = (len(sorted_data) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_data) - 1)
    if f == c:
        return sorted_data[f]
    return sorted_data[f] + (k - f) * (sorted_data[c] - sorted_data[f])


def run_benchmark(
    fn: Callable[[], T],
    config: BenchmarkConfig | None = None,
    name: str = "benchmark",
) -> BenchmarkResult:
    """Run synchronous benchmark."""
    config = config or BenchmarkConfig()
    latencies: list[float] = []
    errors: list[str] = []
    successful = 0

    # Warmup
    for _ in range(config.warmup):
        try:
            fn()
        except Exception:
            pass

    # Measured runs
    start_total = time.perf_counter()
    for _ in range(config.iterations):
        start = time.perf_counter()
        try:
            fn()
            latency = (time.perf_counter() - start) * 1000.0
            latencies.append(latency)
            successful += 1
        except Exception as exc:
            errors.append(str(exc))
    total_time = time.perf_counter() - start_total

    failed = config.iterations - successful
    error_rate = failed / max(1, config.iterations)

    if latencies:
        latency_ms = {f"p{int(p)}": percentile(latencies, p) for p in config.percentiles}
        min_ms = min(latencies)
        max_ms = max(latencies)
        mean_ms = statistics.mean(latencies)
        stdev_ms = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
    else:
        latency_ms = {f"p{int(p)}": 0.0 for p in config.percentiles}
        min_ms = max_ms = mean_ms = stdev_ms = 0.0

    throughput = successful / max(0.001, total_time)

    return BenchmarkResult(
        name=name,
        iterations=config.iterations,
        successful=successful,
        failed=failed,
        error_rate=error_rate,
        latency_ms=latency_ms,
        throughput_per_s=throughput,
        min_ms=min_ms,
        max_ms=max_ms,
        mean_ms=mean_ms,
        stdev_ms=stdev_ms,
        errors=errors[:10],  # Limit error list
    )


async def run_async_benchmark(
    coro_factory: Callable[[], Any],
    config: BenchmarkConfig | None = None,
    name: str = "async_benchmark",
) -> BenchmarkResult:
    """Run async benchmark with concurrency control."""
    config = config or BenchmarkConfig()
    semaphore = asyncio.Semaphore(config.concurrency)
    latencies: list[float] = []
    errors: list[str] = []
    successful = 0

    async def _run_one() -> None:
        nonlocal successful
        async with semaphore:
            start = time.perf_counter()
            try:
                await coro_factory()
                latency = (time.perf_counter() - start) * 1000.0
                latencies.append(latency)
                successful += 1
            except Exception as exc:
                errors.append(str(exc))

    # Warmup
    for _ in range(config.warmup):
        try:
            await _run_one()
        except Exception:
            pass

    # Measured runs
    start_total = time.perf_counter()
    tasks = [_run_one() for _ in range(config.iterations)]
    await asyncio.gather(*tasks, return_exceptions=True)
    total_time = time.perf_counter() - start_total

    failed = config.iterations - successful
    error_rate = failed / max(1, config.iterations)

    if latencies:
        latency_ms = {f"p{int(p)}": percentile(latencies, p) for p in config.percentiles}
        min_ms = min(latencies)
        max_ms = max(latencies)
        mean_ms = statistics.mean(latencies)
        stdev_ms = statistics.stdev(latencies) if len(latencies) > 1 else 0.0
    else:
        latency_ms = {f"p{int(p)}": 0.0 for p in config.percentiles}
        min_ms = max_ms = mean_ms = stdev_ms = 0.0

    throughput = successful / max(0.001, total_time)

    return BenchmarkResult(
        name=name,
        iterations=config.iterations,
        successful=successful,
        failed=failed,
        error_rate=error_rate,
        latency_ms=latency_ms,
        throughput_per_s=throughput,
        min_ms=min_ms,
        max_ms=max_ms,
        mean_ms=mean_ms,
        stdev_ms=stdev_ms,
        errors=errors[:10],
    )


def compare_benchmarks(baseline: BenchmarkResult, candidate: BenchmarkResult) -> dict:
    """Compare two benchmark results."""
    return {
        "latency_change_p50": (
            (candidate.latency_ms.get("p50", 0) - baseline.latency_ms.get("p50", 0))
            / max(1, baseline.latency_ms.get("p50", 1))
            * 100
        ),
        "latency_change_p95": (
            (candidate.latency_ms.get("p95", 0) - baseline.latency_ms.get("p95", 0))
            / max(1, baseline.latency_ms.get("p95", 1))
            * 100
        ),
        "latency_change_p99": (
            (candidate.latency_ms.get("p99", 0) - baseline.latency_ms.get("p99", 0))
            / max(1, baseline.latency_ms.get("p99", 1))
            * 100
        ),
        "throughput_change_pct": (
            (candidate.throughput_per_s - baseline.throughput_per_s)
            / max(0.001, baseline.throughput_per_s)
            * 100
        ),
        "error_rate_change": candidate.error_rate - baseline.error_rate,
    }


def run_suite(
    benchmarks: dict[str, Callable[[], Any]],
    config: BenchmarkConfig | None = None,
) -> dict[str, BenchmarkResult]:
    """Run multiple benchmarks and return results dict."""
    return {name: run_benchmark(fn, config, name) for name, fn in benchmarks.items()}