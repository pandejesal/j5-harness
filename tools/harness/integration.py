"""Cross-project harness wiring (Task 5.1).

Wires the Phase 4 components (router, delegation, skills, latency) into a
unified harness:

- Process-global shared singletons (spec 3.1): one ``HealthTracker`` /
  ``FeedbackLoop`` / ``FallbackChainBuilder`` / ``FreeModelRouter`` /
  ``ZenGatewayAdapter`` / ``MultiTierCache`` so a 429 in one project
  quarantines the model globally (shared Zen IP bucket).
- Per-project contexts (spec 3.2): enabled projects from
  ``reliability.config.json`` get isolated ledgers, skill roots, caches and
  per-project-per-model circuit breakers.
- ``make_router_fn`` (spec 3.3): builds the ``router_fn`` closure that
  implements the ``(prompt, *, task_id, task_type, chain=None, model_id=None)
  -> {"text", "confidence", "model_id"}`` contract used by Orchestrator.run,
  run_consensus and CritiqueLoop.rerun.

Stdlib-only, Windows-safe. No network access at import time.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tools.delegation.ledger import DelegationLedger
from tools.latency.async_engine import CircuitBreaker
from tools.latency.caching import CacheConfig, MultiTierCache
from tools.latency.context_compression import (
    CompressionConfig,
    compress_context,
    estimate_tokens,
)
from tools.router.fallback_chain import FallbackChainBuilder
from tools.router.feedback_loop import FeedbackLoop
from tools.router.free_model_router import FreeModelRouter
from tools.router.cli_gateway import resolve_pure
from tools.router.gateway_adapters import GatewayError, GatewayInterface, ZenGatewayAdapter
from tools.router.health_probe import HealthTracker
from tools.router.model_registry import MODELS, default_chain
from tools.skills.ecosystem.skill_hub import SkillHub

CONFIG_PATH = Path(__file__).resolve().parent.parent / "reliability" / "reliability.config.json"
STATE_CACHE_DIR = Path(__file__).resolve().parent.parent / "state" / "cache"
DEFAULT_TOKEN_BUDGET = 4000

# Role -> registry task type mapping (spec 3.4).
ROLE_TASK_TYPES: dict[str, str] = {
    "coder": "coding",
    "planner": "research",
    "bulk": "analysis",
}

# router_fn contract: (prompt, *, task_id, task_type, chain=None, model_id=None)
# -> {"text", "confidence", "model_id"} (plus "error" on total failure).
RouterFn = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class ProjectContext:
    """Per-project wiring context (spec 3.2)."""

    name: str
    dir: Path
    ledger_path: Path
    cache_path: Path
    skill_roots: list[Path]
    role_chain: list[str]  # from fallbackLadders[role]
    # Side table populated at decompose: {task_id: (skill_identity, inputs)}.
    leaf_skills: dict[str, tuple[str, dict]] = field(default_factory=dict)


@dataclass
class SharedState:
    """Process-global singletons shared across all projects (spec 3.1)."""

    tracker: HealthTracker
    feedback: FeedbackLoop
    chain_builder: FallbackChainBuilder
    router: FreeModelRouter
    adapter: GatewayInterface
    cache: MultiTierCache


@dataclass
class ProjectState:
    """Per-project runtime state: ledger, skill hub, per-model breakers."""

    ctx: ProjectContext
    ledger: DelegationLedger
    skill_hub: SkillHub
    # Per-project-per-model breakers (spec 3.6): keyed by model_id within
    # this project's state, so a failure in wsb-alpha never trips a
    # burgonomics breaker. Equivalent to CircuitBreaker(key=f"{name}:{model}").
    breakers: dict[str, "SyncCircuitBreaker"]


class SyncCircuitBreaker:
    """Sync adapter over the async ``CircuitBreaker`` state (thread-safe).

    Mirrors ``CircuitBreaker.call`` semantics for the sync router_fn
    contract: failures are pruned to the window, the breaker trips open
    after ``failure_threshold`` failures, and a success clears the failure
    history. The wrapped async breaker's ``_failures`` / ``_open_until``
    fields are reused so async and sync views agree.
    """

    def __init__(self, breaker: CircuitBreaker | None = None) -> None:
        self._breaker = breaker or CircuitBreaker()
        self._lock = threading.Lock()

    def is_open(self) -> bool:
        with self._lock:
            return self._breaker.is_open()

    def record_success(self) -> None:
        with self._lock:
            self._breaker._failures.clear()

    def record_failure(self) -> None:
        now = time.time()
        with self._lock:
            self._breaker._failures = [
                t for t in self._breaker._failures if now - t < self._breaker.window_s
            ]
            self._breaker._failures.append(now)
            if len(self._breaker._failures) >= self._breaker.failure_threshold:
                self._breaker._open_until = now + self._breaker.cooldown_s


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load reliability.config.json (defaults to the repo config)."""
    config_path = Path(path) if path else CONFIG_PATH
    with config_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def build_gateway(max_in_flight: int = 1) -> GatewayInterface:
    """Select the dispatch backend.

    ``J5_GATEWAY`` env override: ``cli`` forces real CLI dispatch,
    ``zen`` forces the HTTP adapter, ``auto`` (default) uses real CLI
    dispatch when an opencode binary is found and falls back to Zen HTTP
    otherwise. Auto mode is what makes `j5 run` prompts actually execute.
    """
    from tools.router.cli_gateway import OpencodeCliAdapter, find_opencode_binary

    mode = os.environ.get("J5_GATEWAY", "auto").strip().lower()
    if mode == "zen":
        return ZenGatewayAdapter(max_in_flight=max_in_flight)
    if mode == "cli":
        return OpencodeCliAdapter(max_in_flight=max_in_flight)
    if find_opencode_binary():
        try:
            return OpencodeCliAdapter(max_in_flight=max_in_flight)
        except ValueError:
            pass
    return ZenGatewayAdapter(max_in_flight=max_in_flight)


def build_shared() -> SharedState:
    """Build the process-global shared singletons (spec 3.1).

    One HealthTracker/FeedbackLoop/FallbackChainBuilder/FreeModelRouter/
    gateway/MultiTierCache for the whole process: a 429 recorded
    in one project quarantines the model for every project (shared Zen IP
    bucket). Dispatch is serialized (max_in_flight=1) on both the router
    and the gateway adapter.
    """
    tracker = HealthTracker()
    feedback = FeedbackLoop()
    chain_builder = FallbackChainBuilder(tracker)
    router = FreeModelRouter(
        tracker=tracker,
        feedback=feedback,
        chain_builder=chain_builder,
        max_in_flight=1,
    )
    adapter = build_gateway(max_in_flight=1)
    cache = MultiTierCache(CacheConfig(l2_path=STATE_CACHE_DIR / "l2_cache.jsonl"))
    return SharedState(
        tracker=tracker,
        feedback=feedback,
        chain_builder=chain_builder,
        router=router,
        adapter=adapter,
        cache=cache,
    )


# Process-global singletons (spec 3.1). Built lazily on first use so that
# importing this module (e.g. `j5 status`, `j5 route`, `j5 --help`) never
# creates files or directories as a side effect. Every project still shares
# the same health/feedback/cache state once built.
_SHARED: SharedState | None = None
_SHARED_LOCK = threading.Lock()


def get_shared() -> SharedState:
    """Return the process-global singletons, building them on first call."""
    global _SHARED
    if _SHARED is None:
        with _SHARED_LOCK:
            if _SHARED is None:
                _SHARED = build_shared()
    return _SHARED


def __getattr__(name: str) -> SharedState:
    # PEP 562: keep `from tools.harness.integration import SHARED` working
    # (tests, desktop/TUI/soak call sites) while building lazily.
    if name == "SHARED":
        return get_shared()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def role_task_type(role: str) -> str:
    """Map a harness role to a registry task type (spec 3.4)."""
    return ROLE_TASK_TYPES.get(role.strip().lower(), "coding")


def role_chain_for(config: dict[str, Any], role: str) -> list[str]:
    """Fallback ladder for a role; falls back to the registry default chain."""
    ladder = config.get("fallbackLadders", {}).get(role)
    if ladder:
        return list(ladder)
    return default_chain(role_task_type(role))


def _skill_roots(config: dict[str, Any], proj_dir: Path) -> list[Path]:
    """Project skill root plus any configured bundled root (spec 3.6)."""
    roots = [proj_dir / ".harness" / "skills"]
    bundled = config.get("skills", {}).get("bundled")
    if bundled:
        roots.append(Path(bundled))
    return roots


def build_project_contexts(
    config: dict[str, Any] | None = None,
    role: str = "coder",
) -> list[ProjectContext]:
    """Build a ProjectContext for every enabled project (spec 3.2).

    Only ``projects.*.enabled`` gates inclusion; the project directory is
    not required to exist at build time. Ledger/cache/skill roots live
    under ``<project_dir>/.harness/``.
    """
    config = config or load_config()
    projects = config.get("projects", {})
    dirs = config.get("dirs", {})
    role_chain = role_chain_for(config, role)
    contexts: list[ProjectContext] = []
    for name, proj in projects.items():
        if not proj.get("enabled"):
            continue
        proj_dir = Path(dirs[name])
        contexts.append(
            ProjectContext(
                name=name,
                dir=proj_dir,
                ledger_path=proj_dir / ".harness" / "ledger.jsonl",
                cache_path=proj_dir / ".harness" / "cache",
                skill_roots=_skill_roots(config, proj_dir),
                role_chain=list(role_chain),
            )
        )
    return contexts


def _build_state(ctx: ProjectContext) -> ProjectState:
    """Build per-project runtime state (ledger, skill hub, breakers)."""
    ledger = DelegationLedger(ctx.ledger_path)
    skill_hub = SkillHub(roots=ctx.skill_roots)
    breakers = {model_id: SyncCircuitBreaker(CircuitBreaker()) for model_id in MODELS}
    return ProjectState(ctx=ctx, ledger=ledger, skill_hub=skill_hub, breakers=breakers)


# Module-level cache so repeated make_router_fn calls for the same project
# reuse the same ledger/skill-hub/breaker instances (shared breaker state).
_project_states: dict[tuple[str, str, tuple[str, ...]], ProjectState] = {}
_states_lock = threading.Lock()


def _get_or_build_state(ctx: ProjectContext) -> ProjectState:
    key = (ctx.name, str(ctx.ledger_path), tuple(str(root) for root in ctx.skill_roots))
    with _states_lock:
        state = _project_states.get(key)
        if state is None:
            state = _build_state(ctx)
            _project_states[key] = state
        return state


def build_project_states(config: dict[str, Any] | None = None) -> dict[str, ProjectState]:
    """Build ProjectState for every enabled project.

    ProjectState holds only per-project objects (ledger, skill hub,
    breakers); the shared singletons are process-global via ``SHARED``.
    """
    config = config or load_config()
    return {ctx.name: _get_or_build_state(ctx) for ctx in build_project_contexts(config)}


def _token_budget(config: dict[str, Any]) -> int:
    try:
        return int(config.get("context", {}).get("target_tokens", DEFAULT_TOKEN_BUDGET))
    except (TypeError, ValueError):
        return DEFAULT_TOKEN_BUDGET


def _cache_key(model_id: str | None, task_type: str, prompt: str) -> str:
    """Stable cache key: exact prompt string, normalized (spec 4)."""
    return hashlib.sha256(
        f"{model_id or 'auto'}|{task_type}|{prompt}".encode("utf-8")
    ).hexdigest()


def _candidate_models(
    model_id: str | None,
    chain: list[str] | None,
    ctx: ProjectContext,
    task_type: str,
    shared: SharedState,
) -> list[str]:
    """Ordered dispatch candidates: explicit model > caller chain > role chain > router pick."""
    if model_id:
        return [model_id]
    if chain:
        return list(dict.fromkeys(chain))
    if ctx.role_chain:
        return list(dict.fromkeys(ctx.role_chain))
    try:
        decision = shared.router.pick(task_type)
    except RuntimeError:
        return []
    return decision.chain or [decision.model]


def _extract_text(response: Any) -> str:
    """Extract a text string from a gateway response dict (or passthrough)."""
    if isinstance(response, str):
        return response
    if isinstance(response, dict):
        payload = response.get("payload")
        if isinstance(payload, dict):
            return _extract_text(payload)
        choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            if isinstance(first, dict):
                if isinstance(first.get("text"), str):
                    return first["text"]
                message = first.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    return message["content"]
        for key in ("output", "response", "text", "content"):
            if key in response:
                value = response[key]
                if isinstance(value, str):
                    return value
                if isinstance(value, dict):
                    return _extract_text(value)
                if isinstance(value, list) and value:
                    return _extract_text(value[0])
        return json.dumps(response, default=str)
    return str(response)


def _ensure_breaker(state: ProjectState, model_id: str) -> SyncCircuitBreaker:
    breaker = state.breakers.get(model_id)
    if breaker is None:
        breaker = SyncCircuitBreaker(CircuitBreaker())
        state.breakers[model_id] = breaker
    return breaker


def make_router_fn(
    ctx: ProjectContext,
    shared: SharedState,
    config: dict[str, Any],
) -> RouterFn:
    """Build the router_fn closure for one project context (spec 3.3).

    Contract: ``(prompt, *, task_id, task_type, chain=None, model_id=None)``
    returns ``{"text", "confidence", "model_id"}`` (plus ``"error"`` on
    total failure). Skill leaves short-circuit before the cache; only the
    model-dispatch path is cached (read-only leaves only).

    Flow: skill leaf -> cache hit -> breaker gate -> model pick -> compress
    -> dispatch -> cache set.
    """
    state = _get_or_build_state(ctx)
    budget = _token_budget(config)

    def router_fn(
        prompt: str,
        *,
        task_id: str,
        task_type: str,
        chain: list[str] | None = None,
        model_id: str | None = None,
        on_text=None,
        session_id: str | None = None,
        pure: bool | None = None,
    ) -> dict[str, Any]:
        # Auto-lean lives here so CLI, TUI, and desktop all share one
        # decision point: explicit flags/env win, else short non-code
        # prompts go lean.
        pure, _ = resolve_pure(pure, prompt)
        # 1. Skill leaf: task_id bound to a skill at decompose time.
        leaf = ctx.leaf_skills.get(task_id)
        if leaf is not None:
            identity, inputs = leaf
            result = state.skill_hub.invoke(
                identity, inputs, {"task_id": task_id, "prompt": prompt}
            )
            if result.ok:
                return {
                    "text": result.output,
                    "confidence": 1.0,
                    "model_id": f"skill:{identity}",
                }
            return {
                "text": result.output or "",
                "confidence": 0.0,
                "model_id": f"skill:{identity}",
                "error": result.error or "skill invocation failed",
            }

        # 2. Cache hit (model-dispatch path only).
        cache_key = _cache_key(model_id, task_type, prompt)
        cached = shared.cache.get(cache_key)
        if isinstance(cached, dict):
            return dict(cached)

        # 5. Compress long prompts to the token budget.
        text = prompt
        if estimate_tokens(prompt) > budget:
            text = compress_context(prompt, CompressionConfig(target_tokens=budget)).content

        # 3 + 4 + 6. Breaker gate, model pick, dispatch with fallback.
        last_error: str | None = None
        for candidate in _candidate_models(model_id, chain, ctx, task_type, shared):
            # Config ladders may list models absent from the registry
            # (e.g. muse-spark-1.2-contributor-free); the tracker raises
            # ValueError for unknown models, so skip them outright.
            if candidate not in MODELS:
                continue
            if shared.tracker.is_quarantined(candidate) or shared.tracker.in_retry_after(
                candidate
            ):
                continue
            breaker = _ensure_breaker(state, candidate)
            if breaker.is_open():
                continue
            start = time.monotonic()
            try:
                response = shared.adapter.send(
                    candidate, text, workdir=str(ctx.dir), task_id=task_id,
                    on_text=on_text, session_id=session_id, pure=pure,
                )
            except GatewayError as exc:
                last_error = str(exc)
                latency_ms = (time.monotonic() - start) * 1000.0
                shared.tracker.record_failure(
                    candidate,
                    status_code=exc.status_code,
                    error=str(exc),
                    retry_after_s=exc.retry_after_s,
                    latency_ms=latency_ms,
                )
                breaker.record_failure()
                # Reputation feedback: failures now move the EMA (previously
                # only successes were recorded, so failing models kept their
                # rank). A 3+ consecutive-failure streak counts as a doom
                # loop and halves the score (see feedback_loop).
                try:
                    streak = (shared.tracker.snapshot().get(candidate, {})
                              .get("consecutive_failures", 0))
                except Exception:  # noqa: BLE001 - health read must never break dispatch
                    streak = 0
                shared.feedback.record(candidate, latency_ms, completeness=0.0,
                                       accuracy=0.0, doom_loop=streak >= 3)
                continue  # next chain entry may still be available
            latency_ms = (time.monotonic() - start) * 1000.0
            shared.tracker.record_success(candidate, latency_ms)
            shared.feedback.record(candidate, latency_ms, completeness=1.0, accuracy=1.0)
            breaker.record_success()
            usage = response.get("usage") if isinstance(response, dict) else None
            result = {"text": _extract_text(response), "confidence": 1.0, "model_id": candidate,
                      "session_id": (usage or {}).get("session_id"),
                      "usage": dict(usage) if isinstance(usage, dict) else {}}
            # 7. Cache set (read-only leaves only).
            shared.cache.set(cache_key, result)
            return result

        return {
            "text": "",
            "confidence": 0.0,
            "model_id": model_id,
            "error": last_error or "no available model",
        }

    return router_fn


def run_probe_roundtrip(
    ctx: ProjectContext,
    probe_id: str,
    prompt: str,
    kilo_cfg: dict[str, Any],
) -> dict[str, Any]:
    """Execute Kilo probe round-trip (probes 09-14) (spec 3.5).

    1. Write probe md to kilo.inbox with frontmatter id/sent_ts/deadline_ts/owner.
    2. Record {probe_id: task_id} in ledger.
    3. Invoke antigravity_bridge.py subprocess with --json.
    4. Write receipt to interharness: kilo-to-hermes-{probe_id}.md with matching id.
    5. Return contract dict: {"text", "confidence", "model_id", "error?"}.
    """
    import os
    import subprocess
    import sys
    import time
    from datetime import datetime, timezone

    inbox = Path(kilo_cfg["inbox"])
    interharness = Path(kilo_cfg["interharness"])
    bridge_path = Path(kilo_cfg["bridge_path"])
    print_timeout = int(kilo_cfg["print_timeout"])

    inbox.mkdir(parents=True, exist_ok=True)
    interharness.mkdir(parents=True, exist_ok=True)

    # 1. Write probe md to inbox (atomic .tmp + os.replace)
    sent_ts = time.time()
    deadline_ts = sent_ts + print_timeout + 60  # caller timeout + buffer
    owner = ctx.name
    probe_md = (
        f"---\n"
        f"id: {probe_id}\n"
        f"sent_ts: {sent_ts}\n"
        f"deadline_ts: {deadline_ts}\n"
        f"owner: {owner}\n"
        f"---\n\n"
        f"{prompt}\n"
    )
    probe_path = inbox / f"hermes-to-kilo-{probe_id}.md"
    tmp_path = probe_path.with_suffix(".md.tmp")
    tmp_path.write_text(probe_md, encoding="utf-8")
    os.replace(tmp_path, probe_path)

    # 2. Record in ledger
    state = _get_or_build_state(ctx)
    state.ledger.append("probe", probe_id, {"prompt": prompt, "sent_ts": sent_ts})

    # 3. Bridge subprocess
    with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as tf:
        tf.write(prompt)
        prompt_tmp = Path(tf.name)
    try:
        cmd = [
            sys.executable,
            str(bridge_path),
            "--prompt-file", str(prompt_tmp),
            "--cwd", str(ctx.dir),
            "--print",
            "--output-format", "json",
            "--print-timeout", str(print_timeout),
            "--json",
        ]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(ctx.dir),
            shell=False,
            timeout=print_timeout + 60,
            env=env,
        )
        result = json.loads(proc.stdout)
    finally:
        try:
            prompt_tmp.unlink()
        except OSError:
            pass

    # 4. Write receipt to interharness
    status = result.get("status", "error")
    output = result.get("output", "")
    evidence = result.get("evidence", "")
    receipt_md = (
        f"---\n"
        f"id: {probe_id}\n"
        f"status: {status}\n"
        f"received_ts: {time.time()}\n"
        f"---\n\n"
        f"{output}\n"
    )
    if evidence:
        receipt_md += f"\n---\nEvidence:\n{evidence}\n"
    receipt_path = interharness / f"kilo-to-hermes-{probe_id}.md"
    tmp_receipt = receipt_path.with_suffix(".md.tmp")
    tmp_receipt.write_text(receipt_md, encoding="utf-8")
    os.replace(tmp_receipt, receipt_path)

    # 5. Return contract dict
    if status == "success":
        return {"text": output, "confidence": 1.0, "model_id": "kilo"}
    return {"text": output or "", "confidence": 0.0, "model_id": "kilo", "error": result.get("error", "kilo probe failed")}


__all__ = [
    "CONFIG_PATH",
    "STATE_CACHE_DIR",
    "DEFAULT_TOKEN_BUDGET",
    "ROLE_TASK_TYPES",
    "RouterFn",
    "ProjectContext",
    "SharedState",
    "ProjectState",
    "SyncCircuitBreaker",
    "load_config",
    "build_gateway",
    "build_shared",
    "get_shared",
    "SHARED",
    "role_task_type",
    "role_chain_for",
    "build_project_contexts",
    "build_project_states",
    "make_router_fn",
    "run_probe_roundtrip",
]