"""OpenCode/Hermes integration surface for the skill ecosystem.

Listing, invocation, and wave execution. Skills run in the capability
sandbox; contracts are validated pre-execution (inputs) and
post-execution (outputs). Same-wave skills share no mutable state
(design constraint).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from . import SkillMeta
from .composition import compose_waves
from .contract_test import ContractValidationError, validate_inputs, validate_outputs
from .registry import Registry
from .sandbox import Sandbox
from .skill_loader import discover_skills


@dataclass(frozen=True)
class InvokeResult:
    """Outcome of one skill invocation."""

    ok: bool
    output: str
    error: str | None = None
    timed_out: bool = False
    exit_code: int = 0
    result: dict | None = None


@dataclass(frozen=True)
class WaveResult:
    """Outcome of one execution wave."""

    wave: int
    results: dict[str, InvokeResult] = field(default_factory=dict)


def _build_glue(inputs: dict, context: dict | None) -> str:
    """Append a driver that calls run() and prints the JSON result."""
    inputs_json = json.dumps(inputs)
    context_json = json.dumps(context or {})
    return (
        "\n"
        "import json as _json\n"
        f"__inputs = _json.loads({inputs_json!r})\n"
        f"__context = _json.loads({context_json!r})\n"
        "try:\n"
        "    __result = run(__inputs, __context)\n"
        "except TypeError:\n"
        "    __result = run(__inputs)\n"
        "print(_json.dumps(__result))\n"
    )


def _parse_result(output: str) -> dict | None:
    """Parse the last non-empty line of stdout as a JSON object."""
    for line in reversed(output.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


class SkillHub:
    """Skill listing, invocation, and wave execution."""

    def __init__(self, roots: list[Path] | None = None, policy: dict | None = None) -> None:
        self.roots = [Path(root) for root in (roots or [])]
        self.registry = Registry()
        self.sandbox = Sandbox(policy)
        self._skills: dict[str, SkillMeta] = {}
        if self.roots:
            self._discover()

    def _discover(self) -> None:
        result = discover_skills(self.roots)
        for skill in result.skills:
            self.registry.add(skill)
            self._skills[skill.identity] = skill

    def list_skills(self) -> list[SkillMeta]:
        return sorted(self._skills.values(), key=lambda skill: skill.identity)

    def get(self, identity: str) -> SkillMeta:
        key = identity.casefold()
        try:
            return self._skills[key]
        except KeyError:
            raise KeyError(f"unknown skill {identity!r}") from None

    def _policy_for(self, skill: SkillMeta) -> dict:
        """Per-skill policy: grant the skill directory as read+write root."""
        policy = dict(self.sandbox.policy)
        skill_dir = Path(skill.path).parent
        fs = dict(policy.get("filesystem", {}))
        fs["allow_reads"] = list(fs.get("allow_reads", [])) + [str(skill_dir)]
        fs["allow_writes"] = list(fs.get("allow_writes", [])) + [str(skill_dir)]
        policy["filesystem"] = fs
        return policy

    def invoke(self, identity: str, inputs: dict, context: dict | None = None) -> InvokeResult:
        """Invoke one skill by ns/name with contract validation."""
        skill = self.get(identity)
        try:
            validate_inputs(skill.contract, inputs)
        except ContractValidationError as exc:
            return InvokeResult(ok=False, output="", error=f"input contract violation: {exc}")

        skill_dir = Path(skill.path).parent
        workdir = skill_dir / "work"
        workdir.mkdir(parents=True, exist_ok=True)
        payload_path = skill_dir / "payload" / "main.py"
        if not payload_path.is_file():
            return InvokeResult(ok=False, output="", error=f"payload missing: {payload_path}")
        code = payload_path.read_text(encoding="utf-8")
        try:
            glue = _build_glue(inputs, context)
        except (TypeError, ValueError) as exc:
            return InvokeResult(ok=False, output="", error=f"inputs not JSON-serializable: {exc}")

        result = self.sandbox.run(
            code + glue, workdir, policy=self._policy_for(skill), timeout_ms=None
        )
        if not result.ok:
            return InvokeResult(
                ok=False,
                output=result.output,
                error=result.error,
                timed_out=result.timed_out,
                exit_code=result.exit_code,
            )
        parsed = _parse_result(result.output)
        if parsed is None:
            return InvokeResult(
                ok=False, output=result.output, error="skill produced no JSON result",
                exit_code=result.exit_code,
            )
        try:
            validate_outputs(skill.contract, parsed)
        except ContractValidationError as exc:
            return InvokeResult(
                ok=False, output=result.output, error=f"output contract violation: {exc}",
                exit_code=result.exit_code,
            )
        return InvokeResult(ok=True, output=result.output, result=parsed, exit_code=0)

    def run_waves(
        self, identities: list[str], inputs: dict, context: dict | None = None
    ) -> list[WaveResult]:
        """Execute skills in dependency waves.

        Requested identities are expanded to their transitive
        dependencies from the discovered set. Same-wave skills share no
        mutable state: each wave receives a fresh copy of the context,
        and skills run in isolated worker processes.
        """
        by_identity = {skill.identity: skill for skill in self._skills.values()}
        expanded: dict[str, SkillMeta] = {}
        queue = [self.get(identity) for identity in identities]
        while queue:
            skill = queue.pop()
            if skill.identity in expanded:
                continue
            expanded[skill.identity] = skill
            for dep_id in skill.dependencies:
                dep = by_identity.get(dep_id)
                if dep is not None:
                    queue.append(dep)
        waves = compose_waves(list(expanded.values()))
        wave_results: list[WaveResult] = []
        for wave_index, wave in enumerate(waves):
            wave_context = dict(context or {})
            results: dict[str, InvokeResult] = {}
            for skill in wave:
                results[skill.identity] = self.invoke(skill.identity, inputs, wave_context)
            wave_results.append(WaveResult(wave=wave_index, results=results))
        return wave_results