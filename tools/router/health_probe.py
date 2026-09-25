"""Health tracking: latency, error counts, quarantine with TTL, JSONL history."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

try:
    from tools.router.model_registry import MODELS
except ImportError:  # script-mode fallback: `python tools/router/router_cli.py`
    from model_registry import MODELS  # type: ignore[no-redef]

HISTORY_FILENAME = "history.jsonl"
DEFAULT_QUARANTINE_TTL_S = 300.0


def _default_history_path() -> Path:
    return Path(__file__).resolve().parent / HISTORY_FILENAME


@dataclass
class ModelHealth:
    model_id: str
    total_requests: int = 0
    successes: int = 0
    failures: int = 0
    count_429: int = 0
    count_500: int = 0
    count_502: int = 0
    count_401: int = 0
    count_other: int = 0
    total_latency_ms: float = 0.0
    last_latency_ms: float | None = None
    quarantined_until: float | None = None
    retry_after_until: float | None = None
    consecutive_failures: int = 0
    last_error: str | None = None
    last_check: float | None = None

    @property
    def avg_latency_ms(self) -> float | None:
        if self.successes <= 0:
            return None
        return self.total_latency_ms / self.successes

    @property
    def error_rate(self) -> float:
        if self.total_requests <= 0:
            return 0.0
        return self.failures / self.total_requests

    def to_dict(self, now: float | None = None) -> dict:
        data = asdict(self)
        data["avg_latency_ms"] = self.avg_latency_ms
        data["error_rate"] = round(self.error_rate, 4)
        data["quarantined"] = self.is_quarantined(now)
        return data

    def is_quarantined(self, now: float | None = None) -> bool:
        if self.quarantined_until is None:
            return False
        return (now if now is not None else time.time()) < self.quarantined_until


class HealthTracker:
    """Thread-safe per-model health store with quarantine + JSONL history."""

    def __init__(
        self,
        history_path: Path | str | None = None,
        quarantine_ttl_s: float = DEFAULT_QUARANTINE_TTL_S,
        quarantine_500_threshold: int = 3,
        quarantine_401_threshold: int = 2,
        quarantine_429_threshold: int = 5,
    ) -> None:
        self.history_path = Path(history_path) if history_path else _default_history_path()
        self.quarantine_ttl_s = quarantine_ttl_s
        self.q500 = quarantine_500_threshold
        self.q401 = quarantine_401_threshold
        self.q429 = quarantine_429_threshold
        self._lock = threading.Lock()
        self._health: dict[str, ModelHealth] = {mid: ModelHealth(model_id=mid) for mid in MODELS}

    def _append_history(self, event: dict) -> None:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        except OSError:
            pass  # history is best-effort; never break routing

    def _ensure(self, model_id: str) -> ModelHealth:
        if model_id not in self._health:
            if model_id not in MODELS:
                raise ValueError(f"unknown model {model_id!r}")
            self._health[model_id] = ModelHealth(model_id=model_id)
        return self._health[model_id]

    def record_success(self, model_id: str, latency_ms: float) -> ModelHealth:
        now = time.time()
        with self._lock:
            h = self._ensure(model_id)
            h.total_requests += 1
            h.successes += 1
            h.total_latency_ms += max(0.0, latency_ms)
            h.last_latency_ms = latency_ms
            h.consecutive_failures = 0
            h.last_check = now
            # Re-admit after cooldown: a success clears an expired quarantine.
            if h.quarantined_until is not None and now >= h.quarantined_until:
                h.quarantined_until = None
            snapshot = h.to_dict(now)
        self._append_history({"ts": now, "type": "success", "model": model_id,
                              "latency_ms": latency_ms})
        return snapshot  # type: ignore[return-value]

    def record_failure(
        self,
        model_id: str,
        status_code: int | None = None,
        error: str = "",
        retry_after_s: float | None = None,
        latency_ms: float | None = None,
    ) -> ModelHealth:
        now = time.time()
        with self._lock:
            h = self._ensure(model_id)
            h.total_requests += 1
            h.failures += 1
            h.consecutive_failures += 1
            h.last_error = error or (f"http_{status_code}" if status_code else "unknown")
            h.last_check = now
            if latency_ms is not None:
                h.last_latency_ms = latency_ms
            if status_code == 429:
                h.count_429 += 1
            elif status_code == 500:
                h.count_500 += 1
            elif status_code == 502:
                h.count_502 += 1
            elif status_code == 401:
                h.count_401 += 1
            else:
                h.count_other += 1
            if retry_after_s and retry_after_s > 0:
                h.retry_after_until = now + retry_after_s
            self._maybe_quarantine(h, now)
            snapshot = h.to_dict(now)
        self._append_history({"ts": now, "type": "failure", "model": model_id,
                              "status": status_code, "error": h.last_error,
                              "quarantined": snapshot["quarantined"]})
        return snapshot  # type: ignore[return-value]

    def _maybe_quarantine(self, h: ModelHealth, now: float) -> None:
        ttl = self.quarantine_ttl_s
        # Quarantine-prone models trip faster: longer TTL for auth/server errors.
        if h.count_500 >= self.q500:
            h.quarantined_until = now + ttl * 2
        elif h.count_401 >= self.q401:
            h.quarantined_until = now + ttl * 3
        elif h.count_429 >= self.q429 or h.consecutive_failures >= 5:
            h.quarantined_until = now + ttl

    def quarantine(self, model_id: str, ttl_s: float | None = None) -> None:
        with self._lock:
            h = self._ensure(model_id)
            h.quarantined_until = time.time() + (ttl_s if ttl_s is not None else self.quarantine_ttl_s)

    def release(self, model_id: str) -> None:
        """Clear quarantine + retry-after gates (test cleanup / manual reset).

        Consecutive-failure history is kept — release re-admits the model
        to dispatch without erasing its earned record.
        """
        with self._lock:
            h = self._ensure(model_id)
            h.quarantined_until = None
            h.retry_after_until = None

    def is_quarantined(self, model_id: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            return self._ensure(model_id).is_quarantined(now)

    def in_retry_after(self, model_id: str, now: float | None = None) -> bool:
        now = now if now is not None else time.time()
        with self._lock:
            until = self._ensure(model_id).retry_after_until
        return until is not None and now < until

    def quarantined_models(self) -> list[str]:
        now = time.time()
        with self._lock:
            return [mid for mid, h in self._health.items() if h.is_quarantined(now)]

    def snapshot(self) -> dict[str, dict]:
        now = time.time()
        with self._lock:
            return {mid: h.to_dict(now) for mid, h in self._health.items()}

    # -- asyncio probes ----------------------------------------------------

    async def probe_model(
        self,
        model_id: str,
        gateway: object = None,
        prompt: str = "ping",
        timeout_s: float = 10.0,
    ) -> dict:
        """Probe one model; without a gateway records a no-op check (offline-safe)."""
        if model_id not in MODELS:
            raise ValueError(f"unknown model {model_id!r}")
        start = time.monotonic()
        try:
            if gateway is None:
                await asyncio.sleep(0)  # yield; offline check of stored health
                latency_ms = (time.monotonic() - start) * 1000.0
                return {"model": model_id, "ok": None, "latency_ms": round(latency_ms, 2),
                        "note": "no gateway; stored-health check only",
                        "quarantined": self.is_quarantined(model_id)}
            send = getattr(gateway, "asend", None) or getattr(gateway, "send_async", None)
            if send is None:
                raise AttributeError("gateway has no async send method")
            result = await asyncio.wait_for(send(model_id, prompt), timeout=timeout_s)
            latency_ms = (time.monotonic() - start) * 1000.0
            self.record_success(model_id, latency_ms)
            return {"model": model_id, "ok": True, "latency_ms": round(latency_ms, 2),
                    "result": result}
        except Exception as exc:  # noqa: BLE001 - probe must not raise
            latency_ms = (time.monotonic() - start) * 1000.0
            status = getattr(exc, "status_code", None)
            self.record_failure(model_id, status_code=status, error=str(exc))
            return {"model": model_id, "ok": False, "latency_ms": round(latency_ms, 2),
                    "error": str(exc)}

    async def probe_all(
        self,
        gateway: object = None,
        prompt: str = "ping",
        timeout_s: float = 10.0,
    ) -> list[dict]:
        results = await asyncio.gather(
            *(self.probe_model(mid, gateway, prompt, timeout_s) for mid in MODELS),
            return_exceptions=False,
        )
        return list(results)
