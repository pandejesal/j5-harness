"""Re-run a leaf only when confidence is below threshold (bounded, frozen prompts)."""

from __future__ import annotations

from dataclasses import dataclass

from tools.delegation.delegation_state import TaskNode, TaskState
from tools.delegation.ledger import DelegationLedger


@dataclass
class CritiqueLoop:
    threshold: float = 0.5
    max_retries: int = 2

    def __post_init__(self) -> None:
        if not 0.0 <= self.threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")

    def should_rerun(self, node: TaskNode) -> bool:
        return (
            node.state in (TaskState.NEEDS_CRITIQUE, TaskState.FAILED, TaskState.SUCCEEDED)
            and node.confidence < self.threshold
            and node.attempts < node.max_attempts
            and (node.attempts - 1) < self.max_retries
        )

    def rerun(self, node: TaskNode, router_fn, ledger: DelegationLedger | None = None,
              task_type: str = "coding", chain: list[str] | None = None) -> TaskNode:
        """Re-dispatch with the FROZEN original prompt; never rewrite it."""
        frozen_prompt = node.prompt
        if node.state == TaskState.NEEDS_CRITIQUE:
            node.transition(TaskState.READY)
        elif node.state in (TaskState.FAILED, TaskState.SUCCEEDED):
            # Re-queue via BLOCKED->READY path legality: FAILED->READY allowed;
            # SUCCEEDED is terminal so only NEEDS_CRITIQUE/FAILED normally rerun.
            if node.state == TaskState.FAILED:
                node.transition(TaskState.READY)
            else:
                node.force_state(TaskState.READY)
        elif node.state not in (TaskState.READY,):
            raise ValueError(f"cannot critique node in state {node.state.value}")
        node.transition(TaskState.DISPATCHED)
        node.record_attempt()
        node.transition(TaskState.RUNNING)
        if ledger:
            ledger.append("dispatch", node.task_id,
                          {"prompt": frozen_prompt, "attempt": node.attempts, "critique_rerun": True})
        outcome = router_fn(frozen_prompt, task_id=node.task_id, task_type=task_type, chain=chain or [])
        if outcome is None:
            raise RuntimeError(f"router_fn returned None for leaf {node.task_id}")
        node.set_result(outcome.get("text", ""), float(outcome.get("confidence", 0.0)),
                        outcome.get("model_id"))
        if node.prompt != frozen_prompt:
            raise ValueError("leaf prompt must stay frozen across critique")
        if node.confidence < self.threshold and node.can_retry() and (node.attempts - 1) < self.max_retries:
            node.transition(TaskState.NEEDS_CRITIQUE)
        else:
            node.transition(TaskState.SUCCEEDED)
        if ledger:
            ledger.append("critique", node.task_id,
                          {"confidence": node.confidence, "attempts": node.attempts,
                           "model_id": node.model_id, "text": node.result})
        return node
