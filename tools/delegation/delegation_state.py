"""Task node states, confidence scores, attempt counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TaskState(str, Enum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    NEEDS_CRITIQUE = "needs_critique"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


_VALID_TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY, TaskState.BLOCKED, TaskState.SKIPPED}),
    TaskState.READY: frozenset({TaskState.DISPATCHED, TaskState.BLOCKED, TaskState.SKIPPED}),
    TaskState.DISPATCHED: frozenset({TaskState.RUNNING, TaskState.FAILED, TaskState.BLOCKED}),
    TaskState.RUNNING: frozenset({TaskState.SUCCEEDED, TaskState.FAILED, TaskState.NEEDS_CRITIQUE}),
    TaskState.NEEDS_CRITIQUE: frozenset(
        {TaskState.READY, TaskState.SUCCEEDED, TaskState.FAILED, TaskState.BLOCKED}
    ),
    TaskState.FAILED: frozenset({TaskState.READY, TaskState.BLOCKED}),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.BLOCKED: frozenset({TaskState.READY}),
    TaskState.SKIPPED: frozenset(),
}


def is_valid_transition(frm: TaskState, to: TaskState) -> bool:
    return to in _VALID_TRANSITIONS.get(frm, frozenset())


@dataclass
class TaskNode:
    """One node in a delegation DAG."""

    task_id: str
    prompt: str  # frozen at creation; critique re-runs must reuse it
    depends_on: tuple[str, ...] = ()
    state: TaskState = TaskState.PENDING
    confidence: float = 0.0
    attempts: int = 0
    max_attempts: int = 3
    result: str | None = None
    model_id: str | None = None
    error: dict | None = None

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be non-empty")
        if not self.prompt:
            raise ValueError("prompt must be non-empty (frozen leaf prompt)")
        self.depends_on = tuple(self.depends_on)
        self.confidence = _clamp_confidence(self.confidence)
        if self.attempts < 0:
            raise ValueError("attempts must be >= 0")
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def transition(self, to: TaskState) -> None:
        if not is_valid_transition(self.state, to):
            raise ValueError(f"illegal transition {self.state.value} -> {to.value}")
        self.state = to

    def force_state(self, to: TaskState) -> None:
        """Unconditional set for terminal/blocked handling by orchestrator."""
        self.state = to

    def record_attempt(self) -> int:
        self.attempts += 1
        return self.attempts

    def can_retry(self) -> bool:
        return self.attempts < self.max_attempts

    def set_result(self, result: str, confidence: float, model_id: str | None = None) -> None:
        self.result = result
        self.confidence = _clamp_confidence(confidence)
        self.model_id = model_id

    def set_error(self, error: dict) -> None:
        self.error = dict(error)

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "depends_on": list(self.depends_on),
            "state": self.state.value,
            "confidence": self.confidence,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "result": self.result,
            "model_id": self.model_id,
            "error": self.error,
        }


def _clamp_confidence(value: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"confidence must be numeric, got {value!r}") from None
    if v != v:  # NaN
        raise ValueError("confidence must not be NaN")
    return max(0.0, min(1.0, v))
