"""Domain-aware model router for J5 Harness.

Extends the base router with domain-specific model selection,
fallback ladders, and routing policies.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Optional

from tools.domains.registry import (
    DomainRegistry,
    ProjectRegistry,
    get_domain_registry,
    get_project_registry,
)
from tools.router.free_model_router import FreeModelRouter, RoutingDecision
from tools.router.health_probe import HealthTracker
from tools.router.feedback_loop import FeedbackLoop
from tools.router.fallback_chain import FallbackChainBuilder, ChainEntry
from tools.router.model_registry import MODELS, validate_task_type


@dataclass(frozen=True)
class DomainRoutingDecision:
    """Extended routing decision with domain context."""
    model: str
    endpoint: str
    expected_latency_ms: float
    reason: str
    chain: list[str]
    domain: str
    project: str
    task_type: str


class DomainAwareRouter:
    """Router that selects models based on domain and project context."""

    def __init__(
        self,
        project_name: str,
        tracker: HealthTracker | None = None,
        feedback: FeedbackLoop | None = None,
        chain_builder: FallbackChainBuilder | None = None,
        max_in_flight: int = 1,
    ) -> None:
        self.project_name = project_name
        self.project_registry = get_project_registry()
        self.domain_registry = get_domain_registry()

        self.project = self.project_registry.get_project(project_name)
        self.domain = self.domain_registry.get_domain(self.project.domain)

        self.tracker = tracker or HealthTracker()
        self.feedback = feedback or FeedbackLoop()
        self.chain_builder = chain_builder or FallbackChainBuilder(self.tracker)
        self.max_in_flight = max(1, max_in_flight)
        self._lock = threading.Lock()
        self._in_flight = 0
        self._tiebreak: dict[str, int] = {}

    def pick(self, task_type: str) -> DomainRoutingDecision:
        """Pick best model for task_type within project's domain."""
        task_type = validate_task_type(task_type)

        with self._lock:
            # Use project-specific fallback ladder
            chain = self._build_domain_chain(task_type)
            if not chain:
                raise RuntimeError(
                    f"no available model for task_type {task_type!r} in domain {self.domain.name}"
                )

            top_score = self._chain_score(task_type, chain[0])
            tied = [e for e in chain if abs(self._chain_score(task_type, e) - top_score) <= 0.02]
            idx = self._tiebreak.get(task_type, 0) % len(tied)
            self._tiebreak[task_type] = idx + 1
            chosen = tied[idx]

            return DomainRoutingDecision(
                model=chosen.model_id,
                endpoint=chosen.endpoint,
                expected_latency_ms=chosen.expected_latency_ms,
                reason=("round-robin tiebreak " f"{idx + 1}/{len(tied)}; " if len(tied) > 1 else "") + chosen.reason,
                chain=[e.model_id for e in chain],
                domain=self.domain.name,
                project=self.project.name,
                task_type=task_type,
            )

    def _build_domain_chain(self, task_type: str) -> list[ChainEntry]:
        """Build fallback chain using project's domain-specific ladder."""
        now = __import__("time").time()
        snapshot = self.tracker.snapshot()
        entries: list[tuple[tuple, ChainEntry]] = []

        # Get models from project's fallback ladder for this task_type
        role = self._task_type_to_role(task_type)
        ladder = self.project.get_fallback_ladder(role)

        for rank0, model_id in enumerate(ladder):
            if model_id not in MODELS:
                continue
            info = MODELS[model_id]
            h = snapshot.get(model_id, {})
            quarantined = h.get("quarantined", False)
            in_retry = self.tracker.in_retry_after(model_id, now)
            exhausted = self.chain_builder.quota_exhausted(model_id)
            available = not (quarantined or in_retry or exhausted)

            avg_lat_raw = h.get("avg_latency_ms")
            avg_lat = float(avg_lat_raw) if avg_lat_raw is not None else float(info.expected_latency_ms)
            ema = self.feedback.get_ema(model_id)

            is_primary = 1.0 if model_id in self.domain_registry.get_domain(self.project.domain).models.primary else 0.0
            rank_score = (
                is_primary * 0.4
                + info.weight * 0.2
                + ema * 0.3
                - h.get("error_rate", 0.0) * 0.5
                - min(avg_lat / 20000.0, 0.5) * 0.2
            )

            if not available:
                reason = ("quarantined" if quarantined else "retry-after" if in_retry else "quota-exhausted")
            else:
                reason = f"domain={self.domain.name} ema={ema:.2f} err={h.get('error_rate', 0.0):.2f}"

            entry = ChainEntry(
                model_id=model_id,
                endpoint=self.chain_builder.endpoint_for(model_id, rank0),
                reason=reason,
                expected_latency_ms=round(avg_lat, 1),
            )
            entries.append(((0 if available else 1, -rank_score), entry))

        entries.sort(key=lambda t: t[0])
        chain = [e for _, e in entries]
        chain = [e for e in chain if not e.reason.startswith(("quarantined", "retry-after", "quota-exhausted"))]

        for i, e in enumerate(chain):
            e.endpoint = self.chain_builder.endpoints[i % len(self.chain_builder.endpoints)] if self.chain_builder.endpoints else e.endpoint

        return chain

    def _task_type_to_role(self, task_type: str) -> str:
        """Map task_type to role for fallback ladder lookup."""
        mapping = {
            "coding": "coder",
            "research": "planner",
            "analysis": "planner",
            "conversation": "coder",
        }
        return mapping.get(task_type, "coder")

    def _chain_score(self, task_type: str, entry: ChainEntry) -> float:
        ema = self.feedback.get_ema(entry.model_id)
        return round(ema - min(entry.expected_latency_ms / 20000.0, 0.5) * 0.2, 4)

    def status(self) -> dict:
        with self._lock:
            in_flight = self._in_flight
        return {
            "project": self.project.name,
            "domain": self.domain.name,
            "max_in_flight": self.max_in_flight,
            "in_flight": in_flight,
            "quarantined": self.tracker.quarantined_models(),
            "health": self.tracker.snapshot(),
            "scores": self.feedback.all_scores(),
        }


class MultiProjectRouter:
    """Router that manages per-project routers and routes to the correct one."""

    def __init__(
        self,
        tracker: HealthTracker | None = None,
        feedback: FeedbackLoop | None = None,
        chain_builder: FallbackChainBuilder | None = None,
        max_in_flight: int = 1,
    ) -> None:
        self.tracker = tracker or HealthTracker()
        self.feedback = feedback or FeedbackLoop()
        self.chain_builder = chain_builder or FallbackChainBuilder(self.tracker)
        self.max_in_flight = max_in_flight
        self._routers: dict[str, DomainAwareRouter] = {}
        self._lock = threading.Lock()

    def get_router(self, project_name: str) -> DomainAwareRouter:
        """Get or create router for a project."""
        with self._lock:
            if project_name not in self._routers:
                self._routers[project_name] = DomainAwareRouter(
                    project_name,
                    tracker=self.tracker,
                    feedback=self.feedback,
                    chain_builder=self.chain_builder,
                    max_in_flight=self.max_in_flight,
                )
            return self._routers[project_name]

    def pick(self, project_name: str, task_type: str) -> DomainRoutingDecision:
        """Pick model for a specific project and task type."""
        router = self.get_router(project_name)
        return router.pick(task_type)

    def route_for_project(self, project_name: str) -> DomainAwareRouter:
        """Get the router instance for a project."""
        return self.get_router(project_name)

    def list_projects(self) -> list[str]:
        return list(self._routers.keys())

    def global_status(self) -> dict:
        return {
            "projects": {name: router.status() for name, router in self._routers.items()},
            "shared_health": self.tracker.snapshot(),
            "shared_scores": self.feedback.all_scores(),
        }