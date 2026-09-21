"""Skill ecosystem: models, loader, registry, composition, sandbox, contracts.

Stdlib-only Python 3.12 package. Windows compatible, no network.

Module map (per research/43-build-spec.md):
  __init__.py      models (SkillMeta, Version, VersionRange, Contract, LockEntry)
  skill_loader.py  SKILL.md discovery + TOML frontmatter loading
  registry.py      strict semver 2.0.0 ops + registry + skills.lock.json
  composition.py   Kahn-wave DAG composition
  sandbox.py       capability sandbox (policy enforcement, NOT a trust boundary)
  contract_test.py strict contract validation + self-tests + unittest matrices
  skill_hub.py     OpenCode/Hermes integration surface
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import total_ordering

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# Models (folded into __init__ per build spec)
# ---------------------------------------------------------------------------

_SEMVER_RE = re.compile(
    r"^(?P<major>0|[1-9]\d*)"
    r"\.(?P<minor>0|[1-9]\d*)"
    r"\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<prerelease>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+(?P<build>[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _compare_prerelease(a: str | None, b: str | None) -> int:
    """Semver 2.0.0 prerelease precedence (build metadata ignored)."""
    if a is None and b is None:
        return 0
    if a is None:
        return 1  # release > prerelease
    if b is None:
        return -1
    a_parts = a.split(".")
    b_parts = b.split(".")
    for pa, pb in zip(a_parts, b_parts):
        pa_num = pa.isdigit()
        pb_num = pb.isdigit()
        if pa_num and pb_num:
            if int(pa) != int(pb):
                return -1 if int(pa) < int(pb) else 1
        elif pa_num:
            return -1  # numeric identifiers sort below alphanumeric
        elif pb_num:
            return 1
        else:
            if pa != pb:
                return -1 if pa < pb else 1
    if len(a_parts) != len(b_parts):
        return -1 if len(a_parts) < len(b_parts) else 1
    return 0


@total_ordering
@dataclass(frozen=True, eq=False)
class Version:
    """Strict semver 2.0.0 version (build metadata ignored for precedence)."""

    major: int
    minor: int
    patch: int
    prerelease: str | None = None
    build: str | None = None

    @classmethod
    def parse(cls, text: str) -> "Version":
        if not isinstance(text, str):
            raise ValueError(f"version must be a string, got {type(text).__name__}")
        match = _SEMVER_RE.match(text.strip())
        if not match:
            raise ValueError(f"invalid semver {text!r}")
        return cls(
            major=int(match.group("major")),
            minor=int(match.group("minor")),
            patch=int(match.group("patch")),
            prerelease=match.group("prerelease"),
            build=match.group("build"),
        )

    def __str__(self) -> str:
        text = f"{self.major}.{self.minor}.{self.patch}"
        if self.prerelease is not None:
            text += f"-{self.prerelease}"
        if self.build is not None:
            text += f"+{self.build}"
        return text

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        return (
            (self.major, self.minor, self.patch) == (other.major, other.minor, other.patch)
            and _compare_prerelease(self.prerelease, other.prerelease) == 0
        )

    def __lt__(self, other: "Version") -> bool:
        if not isinstance(other, Version):
            return NotImplemented
        if (self.major, self.minor, self.patch) != (other.major, other.minor, other.patch):
            return (self.major, self.minor, self.patch) < (other.major, other.minor, other.patch)
        return _compare_prerelease(self.prerelease, other.prerelease) < 0

    def __hash__(self) -> int:
        return hash((self.major, self.minor, self.patch, self.prerelease))


@dataclass(frozen=True)
class VersionRange:
    """A semver constraint expression (e.g. ``>=1.2.0,<2.0.0``).

    Parsing/ops live in registry.py; this is the model holder.
    """

    expression: str

    def matches(self, version: Version) -> bool:
        from .registry import satisfies

        return satisfies(version, self.expression)


@dataclass(frozen=True)
class Contract:
    """Input/output schema maps: field name -> strict schema dict."""

    inputs: dict[str, dict] = field(default_factory=dict)
    outputs: dict[str, dict] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillMeta:
    """One loaded skill. Identity key = ``f"{ns}/{name}".casefold()``."""

    namespace: str
    name: str
    version: Version
    capabilities: tuple[str, ...] = ()
    dependencies: dict[str, VersionRange] = field(default_factory=dict)
    contract: Contract = field(default_factory=Contract)
    self_tests: tuple[dict, ...] = ()
    source: str = ""
    path: str = ""
    shadowed_by: str | None = None
    policy: dict | None = None

    def __post_init__(self) -> None:
        if not self.namespace or not self.name:
            raise ValueError("namespace and name must be non-empty")
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "self_tests", tuple(self.self_tests))
        object.__setattr__(self, "dependencies", dict(self.dependencies))

    @property
    def identity(self) -> str:
        return f"{self.namespace}/{self.name}".casefold()


@dataclass(frozen=True)
class LockEntry:
    """One skill row in skills.lock.json."""

    version: str
    sha256: str
    source: str
    dependencies: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Re-exports (imported after models so sibling modules can `from . import ...`)
# ---------------------------------------------------------------------------

from .composition import CycleError, compose_waves, detect_cycles  # noqa: E402
from .contract_test import (  # noqa: E402
    ContractValidationError,
    run_self_tests,
    validate_contract,
    validate_inputs,
    validate_outputs,
    validate_schema,
    validate_value,
)
from .registry import ResolutionError, Registry, parse_constraint, satisfies  # noqa: E402
from .sandbox import Sandbox, SandboxResult, validate_policy  # noqa: E402
from .skill_loader import (  # noqa: E402
    DiscoveryResult,
    ShadowRecord,
    SkillLoadError,
    discover_skills,
    load_skill,
)
from .skill_hub import InvokeResult, SkillHub, WaveResult  # noqa: E402

__all__ = [
    "__version__",
    "Contract",
    "ContractValidationError",
    "CycleError",
    "DiscoveryResult",
    "InvokeResult",
    "LockEntry",
    "Registry",
    "ResolutionError",
    "Sandbox",
    "SandboxResult",
    "ShadowRecord",
    "SkillHub",
    "SkillLoadError",
    "SkillMeta",
    "Version",
    "VersionRange",
    "WaveResult",
    "compose_waves",
    "detect_cycles",
    "discover_skills",
    "load_skill",
    "parse_constraint",
    "run_self_tests",
    "satisfies",
    "validate_contract",
    "validate_inputs",
    "validate_outputs",
    "validate_policy",
    "validate_schema",
    "validate_value",
]