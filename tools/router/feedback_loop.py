"""Feedback loop: score responses, EMA quality per model, degradation trends."""

from __future__ import annotations

import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

try:
    from tools.router.model_registry import MODELS
except ImportError:  # script-mode fallback
    from model_registry import MODELS  # type: ignore[no-redef]

FEEDBACK_FILENAME = "feedback.jsonl"
DEFAULT_ALPHA = 0.3
DEFAULT_WINDOW = 20
LATENCY_NORM_MS = 10000.0


def _default_feedback_path() -> Path:
    return Path(__file__).resolve().parent / FEEDBACK_FILENAME


def score_response(latency_ms: float, completeness: float, accuracy: float) -> float:
    """Blend latency/completeness/accuracy into a [0, 1] score."""
    comp = min(max(completeness, 0.0), 1.0)
    acc = min(max(accuracy, 0.0), 1.0)
    lat_score = max(0.0, 1.0 - max(0.0, latency_ms) / LATENCY_NORM_MS)
    return round(0.4 * lat_score + 0.3 * comp + 0.3 * acc, 4)


@dataclass
class ModelScore:
    model_id: str
    ema: float = 0.5
    count: int = 0
    recent: deque = field(default_factory=lambda: deque(maxlen=DEFAULT_WINDOW))
    degrading: bool = False


class FeedbackLoop:
    """Thread-safe EMA quality tracker with trend-based degradation detection."""

    def __init__(
        self,
        alpha: float = DEFAULT_ALPHA,
        window: int = DEFAULT_WINDOW,
        feedback_path: Path | str | None = None,
    ) -> None:
        self.alpha = alpha
        self.window = window
        self.feedback_path = Path(feedback_path) if feedback_path else _default_feedback_path()
        self._lock = threading.Lock()
        self._scores: dict[str, ModelScore] = {mid: ModelScore(model_id=mid) for mid in MODELS}

    def _append_history(self, event: dict) -> None:
        try:
            self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.feedback_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(event, default=str) + "\n")
        except OSError:
            pass

    def _ensure(self, model_id: str) -> ModelScore:
        if model_id not in self._scores:
            if model_id not in MODELS:
                raise ValueError(f"unknown model {model_id!r}")
            self._scores[model_id] = ModelScore(model_id=model_id)
        return self._scores[model_id]

    def record(
        self,
        model_id: str,
        latency_ms: float,
        completeness: float,
        accuracy: float,
    ) -> dict:
        score = score_response(latency_ms, completeness, accuracy)
        now = time.time()
        with self._lock:
            s = self._ensure(model_id)
            s.count += 1
            s.ema = round(self.alpha * score + (1 - self.alpha) * s.ema, 4)
            recent: deque = s.recent
            if recent.maxlen != self.window:
                recent = deque(recent, maxlen=self.window)
                s.recent = recent
            recent.append(score)
            s.degrading = self._trend_degrading(list(recent))
            snapshot = {"model": model_id, "score": score, "ema": s.ema,
                        "count": s.count, "degrading": s.degrading}
        self._append_history({"ts": now, **snapshot, "latency_ms": latency_ms,
                              "completeness": completeness, "accuracy": accuracy})
        return snapshot

    @staticmethod
    def _trend_degrading(recent: list[float]) -> bool:
        """Degrading if the second half averages clearly below the first half."""
        n = len(recent)
        if n < 6:
            return False
        half = n // 2
        first = sum(recent[:half]) / half
        second = sum(recent[half:]) / (n - half)
        return (first - second) > 0.15 and second < 0.6

    def get_ema(self, model_id: str) -> float:
        with self._lock:
            return self._ensure(model_id).ema

    def all_scores(self) -> dict[str, dict]:
        with self._lock:
            return {
                mid: {"ema": s.ema, "count": s.count,
                      "degrading": s.degrading,
                      "recent": list(s.recent)[-5:]}
                for mid, s in self._scores.items()
            }

    def ema_map(self) -> dict[str, float]:
        with self._lock:
            return {mid: s.ema for mid, s in self._scores.items()}

    def degrading_models(self) -> list[str]:
        with self._lock:
            return [mid for mid, s in self._scores.items() if s.degrading]
