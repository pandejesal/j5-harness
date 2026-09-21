"""SKILL.md discovery + TOML frontmatter loading.

Discovery roots are searched in precedence order (project > user >
bundled by default); later roots shadow earlier ones and the shadowed
entries are recorded. Frontmatter is TOML parsed with tomllib (never
hand-rolled YAML). Load-time validation: well-formed, semver-valid,
self-tests pass, deps exist, no cycles.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from . import Contract, SkillMeta, Version, VersionRange
from .composition import CycleError, detect_cycles
from .contract_test import run_self_tests, validate_schema
from .registry import parse_constraint

FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)

REQUIRED_KEYS = (
    "namespace",
    "name",
    "version",
    "capabilities",
    "dependencies",
    "contract",
    "self_tests",
)

ROOT_PRECEDENCE = ("project", "user", "bundled")


class SkillLoadError(ValueError):
    """Raised when a SKILL.md cannot be loaded or validated."""


@dataclass(frozen=True)
class ShadowRecord:
    """A skill entry shadowed by a higher-precedence root."""

    identity: str
    source: str
    shadowed_by: str


@dataclass(frozen=True)
class DiscoveryResult:
    """Outcome of a multi-root discovery pass."""

    skills: tuple[SkillMeta, ...] = ()
    shadows: tuple[ShadowRecord, ...] = ()


def parse_frontmatter(text: str) -> dict:
    """Extract and parse the TOML frontmatter block from SKILL.md text."""
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise SkillLoadError("missing TOML frontmatter (--- delimited)")
    try:
        data = tomllib.loads(match.group(1))
    except tomllib.TOMLDecodeError as exc:
        raise SkillLoadError(f"frontmatter TOML parse failed: {exc}") from None
    if not isinstance(data, dict):
        raise SkillLoadError("frontmatter must be a TOML table")
    return data


def load_skill(path: str | Path, source: str = "") -> SkillMeta:
    """Load and validate one SKILL.md into a SkillMeta.

    Raises SkillLoadError on malformed frontmatter, invalid semver,
    invalid contract schemas, or failing self-tests.
    """
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SkillLoadError(f"cannot read {path}: {exc}") from None
    data = parse_frontmatter(text)
    missing = [key for key in REQUIRED_KEYS if key not in data]
    if missing:
        raise SkillLoadError(f"{path}: missing frontmatter keys {missing}")
    try:
        namespace = str(data["namespace"])
        name = str(data["name"])
        version = Version.parse(str(data["version"]))
        capabilities = tuple(str(cap) for cap in data["capabilities"])
        dependencies: dict[str, VersionRange] = {}
        for dep_id, expr in data["dependencies"].items():
            parse_constraint(str(expr))  # validate expression syntax at load
            dependencies[str(dep_id)] = VersionRange(str(expr))
        contract_data = data["contract"]
        inputs = dict(contract_data.get("inputs", {}))
        outputs = dict(contract_data.get("outputs", {}))
        for schema in inputs.values():
            validate_schema(schema)
        for schema in outputs.values():
            validate_schema(schema)
        contract = Contract(inputs=inputs, outputs=outputs)
        self_tests = tuple(dict(test) for test in data["self_tests"])
    except (TypeError, ValueError, AttributeError) as exc:
        raise SkillLoadError(f"{path}: invalid frontmatter: {exc}") from None
    meta = SkillMeta(
        namespace=namespace,
        name=name,
        version=version,
        capabilities=capabilities,
        dependencies=dependencies,
        contract=contract,
        self_tests=self_tests,
        source=source,
        path=str(path),
    )
    failures = run_self_tests(meta)
    if failures:
        raise SkillLoadError(f"{path}: self-tests failed: {'; '.join(failures)}")
    return meta


def validate_skill(meta: SkillMeta) -> list[str]:
    """Run load-time self-tests. Returns failure messages (empty = valid)."""
    return run_self_tests(meta)


def validate_dependencies(skills: list[SkillMeta]) -> list[str]:
    """Check that every dependency exists and the graph is acyclic.

    Returns failure messages (empty = valid).
    """
    failures: list[str] = []
    known = {skill.identity for skill in skills}
    for skill in skills:
        for dep_id in skill.dependencies:
            if dep_id not in known:
                failures.append(f"{skill.identity}: unknown dependency {dep_id!r}")
    try:
        detect_cycles(skills)
    except CycleError as exc:
        failures.append(str(exc))
    return failures


def discover_skills(
    roots: dict[str, str | Path] | Sequence[str | Path],
    precedence: tuple[str, ...] = ROOT_PRECEDENCE,
) -> DiscoveryResult:
    """Discover SKILL.md files across roots with precedence shadowing.

    `roots` may be a dict {root_id: path} or a list of paths (ids
    derived from the directory name). Roots named in `precedence` are
    searched in that order; later roots shadow earlier ones and the
    shadowed entries are recorded. Fail-closed: any load error or
    dependency validation failure raises SkillLoadError.
    """
    if isinstance(roots, dict):
        root_map = {str(root_id): Path(root_path) for root_id, root_path in roots.items()}
    else:
        root_map = {Path(root_path).name: Path(root_path) for root_path in roots}
    ordered = [
        (root_id, root_map[root_id]) for root_id in precedence if root_id in root_map
    ]
    ordered.extend(
        (root_id, root_path)
        for root_id, root_path in root_map.items()
        if root_id not in precedence
    )

    skills: dict[str, SkillMeta] = {}
    shadows: list[ShadowRecord] = []
    errors: list[str] = []
    for root_id, root in ordered:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                meta = load_skill(skill_md, source=root_id)
            except SkillLoadError as exc:
                errors.append(str(exc))
                continue
            existing = skills.get(meta.identity)
            if existing is not None:
                shadows.append(
                    ShadowRecord(
                        identity=meta.identity,
                        source=existing.source,
                        shadowed_by=root_id,
                    )
                )
            skills[meta.identity] = meta
    if errors:
        raise SkillLoadError("; ".join(errors))
    failures = validate_dependencies(list(skills.values()))
    if failures:
        raise SkillLoadError("; ".join(failures))
    return DiscoveryResult(skills=tuple(skills.values()), shadows=tuple(shadows))