"""Single source of truth for free-tier model metadata.

Everything else (fallback chains, router, CLI) must read this registry;
no hardcoded model list is allowed elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TASK_TYPES: tuple[str, ...] = ("coding", "research", "conversation", "analysis")

# Multiple Zen gateway endpoints for endpoint-aware failover.
ZEN_ENDPOINTS: tuple[str, ...] = (
    "https://zen.example.com/v1",
    "https://zen-backup.example.com/v1",
)


@dataclass(frozen=True)
class ModelInfo:
    model_id: str
    description: str
    capabilities: tuple[str, ...]
    task_types: tuple[str, ...]
    weight: float
    requests_per_minute: int
    requests_per_day: int
    stable: bool
    expected_latency_ms: int
    notes: str = ""


MODELS: dict[str, ModelInfo] = {
    "mimo-v2.5-free": ModelInfo(
        model_id="mimo-v2.5-free",
        description="Stable, strong coding model.",
        capabilities=("coding", "analysis"),
        task_types=("coding", "analysis", "research", "conversation"),
        weight=1.0,
        requests_per_minute=20,
        requests_per_day=1000,
        stable=True,
        expected_latency_ms=2500,
        notes="stable, strong coding",
    ),
    "nemotron-3-ultra-free": ModelInfo(
        model_id="nemotron-3-ultra-free",
        description="Stable, strong research model.",
        capabilities=("research", "analysis"),
        task_types=("research", "analysis", "coding", "conversation"),
        weight=0.9,
        requests_per_minute=15,
        requests_per_day=800,
        stable=True,
        expected_latency_ms=3000,
        notes="stable, strong research",
    ),
    "ling-3.0-flash-fin-free": ModelInfo(
        model_id="ling-3.0-flash-fin-free",
        description="Stable conversation model.",
        capabilities=("conversation",),
        task_types=("conversation", "research", "analysis", "coding"),
        weight=0.8,
        requests_per_minute=30,
        requests_per_day=1500,
        stable=True,
        expected_latency_ms=1500,
        notes="stable, conversation",
    ),
    "muse-spark-1.3-contributor-free": ModelInfo(
        model_id="muse-spark-1.3-contributor-free",
        description="Quarantine-prone; recurring 500 errors.",
        capabilities=("coding", "conversation"),
        task_types=("coding", "conversation", "analysis", "research"),
        weight=0.5,
        requests_per_minute=10,
        requests_per_day=400,
        stable=False,
        expected_latency_ms=3500,
        notes="500 errors, quarantine-prone",
    ),
    "laguna-s-2.1-free": ModelInfo(
        model_id="laguna-s-2.1-free",
        description="Quarantine-prone; recurring 401 errors.",
        capabilities=("conversation",),
        task_types=("conversation", "research", "coding", "analysis"),
        weight=0.4,
        requests_per_minute=10,
        requests_per_day=300,
        stable=False,
        expected_latency_ms=2000,
        notes="401 errors, quarantine-prone",
    ),
}

# Per-task-type affinity in [0, 1]; combined with weight for ordering.
TASK_AFFINITY: dict[str, dict[str, float]] = {
    "coding": {
        "mimo-v2.5-free": 1.0,
        "muse-spark-1.3-contributor-free": 0.7,
        "nemotron-3-ultra-free": 0.6,
        "ling-3.0-flash-fin-free": 0.4,
        "laguna-s-2.1-free": 0.3,
    },
    "research": {
        "nemotron-3-ultra-free": 1.0,
        "mimo-v2.5-free": 0.7,
        "ling-3.0-flash-fin-free": 0.6,
        "muse-spark-1.3-contributor-free": 0.4,
        "laguna-s-2.1-free": 0.3,
    },
    "conversation": {
        "ling-3.0-flash-fin-free": 1.0,
        "mimo-v2.5-free": 0.7,
        "nemotron-3-ultra-free": 0.6,
        "muse-spark-1.3-contributor-free": 0.4,
        "laguna-s-2.1-free": 0.3,
    },
    "analysis": {
        "nemotron-3-ultra-free": 0.9,
        "mimo-v2.5-free": 0.9,
        "ling-3.0-flash-fin-free": 0.6,
        "muse-spark-1.3-contributor-free": 0.5,
        "laguna-s-2.1-free": 0.3,
    },
}


def validate_task_type(task_type: str) -> str:
    normalized = task_type.strip().lower()
    if normalized not in TASK_TYPES:
        raise ValueError(f"unknown task_type {task_type!r}; expected one of {list(TASK_TYPES)}")
    return normalized


def get_model(model_id: str) -> ModelInfo:
    try:
        return MODELS[model_id]
    except KeyError:
        raise ValueError(f"unknown model {model_id!r}") from None


def all_models() -> list[ModelInfo]:
    return list(MODELS.values())


def affinity(task_type: str, model_id: str) -> float:
    return TASK_AFFINITY[validate_task_type(task_type)].get(model_id, 0.0)


def score_for_task(task_type: str, model_id: str) -> float:
    """Static priority score: affinity blended with registry weight."""
    info = get_model(model_id)
    return round(affinity(task_type, model_id) * 0.7 + info.weight * 0.3, 4)


def models_for_task(task_type: str) -> list[ModelInfo]:
    """Registry-driven candidate list for a task type, best first."""
    task_type = validate_task_type(task_type)
    candidates = [m for m in MODELS.values() if task_type in m.task_types]
    candidates.sort(key=lambda m: score_for_task(task_type, m.model_id), reverse=True)
    return candidates


def default_chain(task_type: str) -> list[str]:
    """Static fallback order (before health/EMA reordering)."""
    return [m.model_id for m in models_for_task(task_type)]
