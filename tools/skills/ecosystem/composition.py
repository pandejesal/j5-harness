"""Kahn-wave DAG composition for skill dependencies.

Wave k contains every skill whose dependencies all live in waves < k.
In-wave order is sorted by identity for determinism. A diamond (two
paths to the same skill) executes the skill exactly once. If the
algorithm exhausts without scheduling every skill, the remainder is
exactly the set of skills participating in dependency cycles.
"""

from __future__ import annotations

from . import SkillMeta


class CycleError(ValueError):
    """Raised when the dependency graph contains cycles.

    Attributes:
        cycle_nodes: frozenset of identities participating in a cycle.
    """

    def __init__(self, cycle_nodes: frozenset[str]) -> None:
        self.cycle_nodes = frozenset(cycle_nodes)
        super().__init__(
            "dependency cycle detected among: " + ", ".join(sorted(self.cycle_nodes))
        )


def _graph(skills: list[SkillMeta]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build (deps, dependents) adjacency maps keyed by identity.

    Raises ValueError when a skill depends on an identity that is not
    present in the provided set (fail-closed; missing deps are not
    cycles and must be reported distinctly).
    """
    by_identity = {skill.identity: skill for skill in skills}
    deps: dict[str, set[str]] = {}
    dependents: dict[str, set[str]] = {}
    for skill in skills:
        identity = skill.identity
        deps.setdefault(identity, set()).update(skill.dependencies.keys())
        dependents.setdefault(identity, set())
    for identity, dep_ids in deps.items():
        for dep_id in dep_ids:
            if dep_id not in by_identity:
                raise ValueError(f"skill {identity!r} depends on unknown skill {dep_id!r}")
            dependents.setdefault(dep_id, set()).add(identity)
    return deps, dependents


def detect_cycles(skills: list[SkillMeta]) -> set[str]:
    """Return the set of identities participating in dependency cycles."""
    deps, dependents = _graph(skills)
    indegree = {identity: len(dep_ids) for identity, dep_ids in deps.items()}
    ready = {identity for identity, degree in indegree.items() if degree == 0}
    processed: set[str] = set()
    while ready:
        node = ready.pop()
        processed.add(node)
        for dependent in dependents.get(node, ()):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.add(dependent)
    return set(indegree) - processed


def compose_waves(skills: list[SkillMeta]) -> list[list[SkillMeta]]:
    """Topologically order skills into execution waves.

    Wave k contains every skill whose dependencies are all in waves < k.
    In-wave order is sorted by identity for determinism. Raises
    CycleError when the graph has cycles (the remainder after Kahn
    exhaustion is exactly the cycle node set).
    """
    deps, dependents = _graph(skills)
    by_identity = {skill.identity: skill for skill in skills}
    indegree = {identity: len(dep_ids) for identity, dep_ids in deps.items()}
    ready = sorted(identity for identity, degree in indegree.items() if degree == 0)
    waves: list[list[SkillMeta]] = []
    processed: set[str] = set()
    while ready:
        wave = [by_identity[identity] for identity in ready]
        waves.append(wave)
        processed.update(ready)
        next_ready: set[str] = set()
        for node in ready:
            for dependent in dependents.get(node, ()):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    next_ready.add(dependent)
        ready = sorted(next_ready)
    remainder = set(indegree) - processed
    if remainder:
        raise CycleError(frozenset(remainder))
    return waves