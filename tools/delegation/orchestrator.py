"""Decompose a task into a DAG, track via ledger, route leaves via router chains."""

from __future__ import annotations

from dataclasses import dataclass, field

from tools.delegation.delegation_state import TaskNode, TaskState
from tools.delegation.ledger import DelegationLedger
from tools.delegation.self_healing import CycleDetector, structured_error


@dataclass
class DelegationDAG:
    root_id: str
    nodes: dict[str, TaskNode] = field(default_factory=dict)

    def leaves(self) -> list[TaskNode]:
        depended_upon = {d for n in self.nodes.values() for d in n.depends_on}
        return [n for tid, n in self.nodes.items() if tid not in depended_upon or not n.depends_on and tid != self.root_id]

    def topological_order(self) -> list[str]:
        indeg = {tid: 0 for tid in self.nodes}
        children: dict[str, list[str]] = {tid: [] for tid in self.nodes}
        for tid, node in self.nodes.items():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"task {tid} depends on unknown {dep!r}")
                indeg[tid] += 1
                children[dep].append(tid)
        queue = sorted(t for t, d in indeg.items() if d == 0)
        order: list[str] = []
        while queue:
            tid = queue.pop(0)
            order.append(tid)
            for child in sorted(children[tid]):
                indeg[child] -= 1
                if indeg[child] == 0:
                    queue.append(child)
        if len(order) != len(self.nodes):
            raise ValueError("cycle detected in delegation DAG")
        return order


class Orchestrator:
    """Owns decompose + dispatch + result logging.

    router_fn: callable(prompt, *, task_id, task_type, chain) -> dict with
      keys: text (str), confidence (float), model_id (str|None).
    chain: optional ordered model-id list (router fallback chain); passed
      through to router_fn for observability.
    """

    def __init__(self, ledger: DelegationLedger, router_fn=None, chain: list[str] | None = None) -> None:
        self.ledger = ledger
        self.router_fn = router_fn
        self.chain = list(chain) if chain else []

    def decompose(
        self,
        root_prompt: str,
        leaves: list[tuple[str, str]] | list[dict],
        root_id: str = "root",
    ) -> DelegationDAG:
        """Split root_prompt into leaf nodes. Leaves: (task_id, prompt) pairs or dicts."""
        dag = DelegationDAG(root_id=root_id)
        root = TaskNode(task_id=root_id, prompt=root_prompt)
        dag.nodes[root_id] = root
        detector = CycleDetector()
        for leaf in leaves:
            if isinstance(leaf, dict):
                tid, prompt = leaf["task_id"], leaf["prompt"]
                deps = tuple(leaf.get("depends_on", ()))
            else:
                tid, prompt = leaf
                deps = ()
            if tid in dag.nodes:
                raise ValueError(f"duplicate task_id {tid!r}")
            dag.nodes[tid] = TaskNode(task_id=tid, prompt=prompt, depends_on=deps)
            for dep in deps:
                detector.add_edge(tid, dep)
                if detector.has_cycle():
                    raise ValueError(f"cycle detected adding edge {tid} -> {dep}")
        # Validate full graph (unknown deps / A->B->C->A loops).
        dag.topological_order()
        self.ledger.append(
            "decompose",
            root_id,
            {"root_prompt": root_prompt, "leaves": [n.to_dict() for t, n in dag.nodes.items() if t != root_id]},
        )
        return dag

    def default_chain_for(self, task_type: str = "coding") -> list[str]:
        """Registry truth for fallback order (import-only; never hardcode)."""
        try:
            from tools.router.model_registry import default_chain
        except ImportError:  # script-mode fallback
            from tools.router.model_registry import default_chain  # type: ignore
        return [m for m in default_chain(task_type)]

    def run(self, dag: DelegationDAG, task_type: str = "coding", max_in_flight: int = 1) -> DelegationDAG:
        if self.router_fn is None:
            raise ValueError("no router_fn configured")
        if max_in_flight < 1:
            raise ValueError("max_in_flight must be >= 1 (serialized to 1 by default)")
        chain = self.chain or self.default_chain_for(task_type)
        for tid in dag.topological_order():
            if tid == dag.root_id:
                continue
            node = dag.nodes[tid]
            # Skip leaves whose deps did not succeed.
            failed_dep = next(
                (d for d in node.depends_on if dag.nodes[d].state != TaskState.SUCCEEDED),
                None,
            )
            if node.depends_on and failed_dep is not None:
                node.force_state(TaskState.BLOCKED)
                self.ledger.append("blocked", tid, {"reason": f"dependency {failed_dep} not succeeded"})
                continue
            node.transition(TaskState.READY)
            node.transition(TaskState.DISPATCHED)
            node.record_attempt()
            node.transition(TaskState.RUNNING)
            self.ledger.append("dispatch", tid, {"prompt": node.prompt, "chain": chain, "attempt": node.attempts})
            try:
                # Serialized: 1 in-flight by default (shared Zen free-tier key).
                outcome = self.router_fn(node.prompt, task_id=tid, task_type=task_type, chain=chain)
                text = outcome.get("text", "")
                conf = float(outcome.get("confidence", 0.0))
                node.set_result(text, conf, outcome.get("model_id"))
                if conf < 0.5:
                    node.transition(TaskState.NEEDS_CRITIQUE)
                else:
                    node.transition(TaskState.SUCCEEDED)
                self.ledger.append(
                    "result", tid, {"model_id": node.model_id, "confidence": node.confidence, "text": text}
                )
            except Exception as exc:  # structured error, never raw raise
                err = structured_error("router-error", str(exc), task_id=tid)
                node.set_error(err)
                node.transition(TaskState.FAILED)
                self.ledger.append("error", tid, err)
        return dag
