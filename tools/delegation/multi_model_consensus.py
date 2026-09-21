"""Fan out one leaf to 3 models; critic tie-break; CRITICAL blocks.

Shared Zen free-tier key: serialized to 1 in-flight by default.
Kilo traffic excluded (own model): any model id containing "kilo"
is filtered out before fan-out.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _exclude_kilo(model_ids: list[str]) -> list[str]:
    return [m for m in model_ids if "kilo" not in m.lower()]


def default_fanout_models(task_type: str = "coding", n: int = 3) -> list[str]:
    """Top-n registry models for task_type, Kilo excluded."""
    from tools.router.model_registry import default_chain

    return _exclude_kilo(default_chain(task_type))[:n]


@dataclass
class ConsensusResult:
    task_id: str
    winner_model: str | None
    text: str | None
    confidence: float
    agreed: bool
    blocked: bool
    findings: list[dict] = field(default_factory=list)
    votes: list[dict] = field(default_factory=list)


def _has_critical(findings: list[dict]) -> bool:
    return any(str(f.get("severity", "")).upper() == "CRITICAL" for f in findings)


def run_consensus(
    task_id: str,
    prompt: str,
    router_fn,
    critic_fn=None,
    task_type: str = "coding",
    models: list[str] | None = None,
    max_in_flight: int = 1,
) -> ConsensusResult:
    """Fan out one frozen leaf prompt to 3 models, serialized (1 in-flight).

    router_fn(prompt, *, task_id, task_type, model_id, chain) -> dict(text, confidence).
    critic_fn(votes) -> dict(winner_index int | None, findings list[{severity,...}]).
    CRITICAL finding in critic findings blocks the leaf.
    """
    if max_in_flight != 1:
        raise ValueError("shared Zen key: max_in_flight must be 1 (serialized fan-out)")
    chain = _exclude_kilo(list(models) if models else default_fanout_models(task_type))
    if len(chain) < 3:
        raise ValueError(f"need 3 non-Kilo models for consensus, got {chain}")
    chain = chain[:3]

    votes: list[dict] = []
    for model_id in chain:  # serialized: 1 in-flight
        outcome = router_fn(prompt, task_id=task_id, task_type=task_type, model_id=model_id, chain=chain)
        votes.append({
            "model_id": model_id,
            "text": outcome.get("text", ""),
            "confidence": float(outcome.get("confidence", 0.0)),
        })

    texts = {v["text"] for v in votes}
    if len(texts) == 1:
        best = max(votes, key=lambda v: v["confidence"])
        return ConsensusResult(task_id, best["model_id"], best["text"],
                               best["confidence"], True, False, [], votes)

    # Disagreement -> critic tie-break.
    findings: list[dict] = []
    winner_index: int | None = None
    if critic_fn is not None:
        verdict = critic_fn(votes) or {}
        winner_index = verdict.get("winner_index")
        findings = list(verdict.get("findings", []))
    if _has_critical(findings):
        return ConsensusResult(task_id, None, None, 0.0, False, True, findings, votes)
    if winner_index is None or not 0 <= winner_index < len(votes):
        winner = max(votes, key=lambda v: v["confidence"])
    else:
        winner = votes[winner_index]
    return ConsensusResult(task_id, winner["model_id"], winner["text"],
                           winner["confidence"], False, False, findings, votes)
