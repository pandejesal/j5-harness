"""Strict semver 2.0.0 operations + skill registry + skills.lock.json.

Hand-rolled per research/43-build-spec.md (no `packaging` dependency):
ops ==, >=, <=, >, <, ~=, ^; comma = AND; prereleases excluded unless
the constraint names one; NO backtracking — resolution fails with the
conflicting constraint set and the skills that introduced them.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import SkillMeta, Version

LOCKFILE_VERSION = 1

_OP_RE = re.compile(r"^(==|>=|<=|>|<|~=|\^)\s*(.+)$")


class ResolutionError(ValueError):
    """Raised when dependency resolution fails (conflict or missing)."""


def parse_constraint(expression: str) -> list[tuple[str, Version]]:
    """Parse a comma-AND constraint expression into (op, version) pairs."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("constraint expression must be a non-empty string")
    clauses: list[tuple[str, Version]] = []
    for raw in expression.split(","):
        part = raw.strip()
        if not part:
            raise ValueError(f"empty clause in constraint {expression!r}")
        match = _OP_RE.match(part)
        if not match:
            raise ValueError(f"unsupported operator in constraint clause {part!r}")
        op, version_text = match.group(1), match.group(2).strip()
        clauses.append((op, Version.parse(version_text)))
    return clauses


def expand_constraint(op: str, version: Version) -> list[tuple[str, Version]]:
    """Expand ~= and ^ into equivalent >=,< clause pairs."""
    if op == "~=":
        # ~=x.y.z -> >=x.y.z,<x.(y+1).0
        return [(">=", version), ("<", Version(version.major, version.minor + 1, 0))]
    if op == "^":
        # ^x.y.z -> >=x.y.z,<next-major (or next-minor/next-patch for 0.x)
        if version.major > 0:
            upper = Version(version.major + 1, 0, 0)
        elif version.minor > 0:
            upper = Version(0, version.minor + 1, 0)
        else:
            upper = Version(0, 0, version.patch + 1)
        return [(">=", version), ("<", upper)]
    return [(op, version)]


def _clause_matches(version: Version, op: str, target: Version) -> bool:
    if version.prerelease is not None and target.prerelease is None:
        # Semver 2.0.0 rule 9: prereleases are excluded unless named.
        return False
    if op == "==":
        return version == target
    if op == ">=":
        return version >= target
    if op == "<=":
        return version <= target
    if op == ">":
        return version > target
    if op == "<":
        return version < target
    raise ValueError(f"unexpected operator {op!r}")


def satisfies(version: Version, expression: str) -> bool:
    """True when `version` satisfies the comma-AND constraint expression."""
    for op, target in parse_constraint(expression):
        for sub_op, sub_target in expand_constraint(op, target):
            if not _clause_matches(version, sub_op, sub_target):
                return False
    return True


def hash_dir(directory: Path, exclude: Path | None = None) -> str:
    """SHA-256 over every file under `directory` (sorted, deterministic).

    `exclude` (e.g. the lockfile itself) is skipped. Fails closed on
    unreadable files.
    """
    hasher = hashlib.sha256()
    exclude_resolved = exclude.resolve() if exclude is not None else None
    for path in sorted(directory.rglob("*")):
        if not path.is_file():
            continue
        if exclude_resolved is not None and path.resolve() == exclude_resolved:
            continue
        rel = path.relative_to(directory).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\x00")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def hash_skill(skill_dir: Path, exclude: Path | None = None) -> str:
    """SHA-256 over SKILL.md plus the payload directory (deterministic)."""
    hasher = hashlib.sha256()
    targets: list[Path] = []
    skill_md = skill_dir / "SKILL.md"
    if skill_md.is_file():
        targets.append(skill_md)
    payload = skill_dir / "payload"
    if payload.is_dir():
        targets.extend(sorted(p for p in payload.rglob("*") if p.is_file()))
    for path in targets:
        if exclude is not None and path.resolve() == exclude.resolve():
            continue
        rel = path.relative_to(skill_dir).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\x00")
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                hasher.update(chunk)
    return hasher.hexdigest()


def _root_relative(path: Path, root: Path) -> str:
    """Forward-slash root-relative path for lockfile storage."""
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ValueError(f"{path} is outside root {root}") from None
    return rel.as_posix()


class Registry:
    """Index of skills by casefolded ns/name with semver resolution."""

    def __init__(self) -> None:
        self._skills: dict[str, dict[str, SkillMeta]] = {}

    def add(self, skill: SkillMeta) -> None:
        versions = self._skills.setdefault(skill.identity, {})
        versions[str(skill.version)] = skill

    def versions(self, identity: str) -> list[Version]:
        key = identity.casefold()
        if key not in self._skills:
            return []
        return sorted(Version.parse(v) for v in self._skills[key])

    def resolve(self, identity: str, constraints: list[tuple[str, str]]) -> SkillMeta:
        """Resolve the max version satisfying ALL (expression, introducer) pairs.

        No backtracking: the first conflicting constraint set fails with
        ResolutionError naming the introducing skills.
        """
        key = identity.casefold()
        available = self._skills.get(key)
        if not available:
            raise ResolutionError(f"no versions registered for {identity!r}")
        candidates = [Version.parse(v) for v in available]
        applied: list[tuple[str, str]] = []
        for expression, introducer in constraints:
            expanded: list[tuple[str, Version]] = []
            for op, target in parse_constraint(expression):
                expanded.extend(expand_constraint(op, target))
            applied.append((expression, introducer))
            candidates = [
                v for v in candidates
                if all(_clause_matches(v, sub_op, sub_target) for sub_op, sub_target in expanded)
            ]
            if not candidates:
                conflict = ", ".join(f"{expr} (from {intro})" for expr, intro in applied)
                raise ResolutionError(f"no version of {identity!r} satisfies {conflict}")
        best = max(candidates)
        return available[str(best)]

    def resolve_all(self, skills: list[SkillMeta]) -> dict[str, SkillMeta]:
        """Resolve the full dependency closure to one version per identity.

        Every constraint on an identity (from any skill that depends on
        it) is applied together; a conflict raises ResolutionError
        naming the introducing skills. Dependency walking uses the max
        registered version of each dependency.
        """
        wanted: dict[str, list[tuple[str, str]]] = {}
        queue = list(skills)
        seen: set[str] = set()
        while queue:
            skill = queue.pop()
            identity = skill.identity
            if identity in seen:
                continue
            seen.add(identity)
            wanted.setdefault(identity, [])
            for dep_id, dep_range in skill.dependencies.items():
                wanted.setdefault(dep_id, []).append((dep_range.expression, identity))
                dep_versions = self._skills.get(dep_id)
                if dep_versions:
                    best = max(Version.parse(v) for v in dep_versions)
                    queue.append(dep_versions[str(best)])
        resolved: dict[str, SkillMeta] = {}
        for identity, constraints in wanted.items():
            resolved[identity] = self.resolve(identity, constraints)
        return resolved

    def write_lockfile(
        self,
        root: Path,
        skills: list[SkillMeta],
        roots: list[Path] | None = None,
        lock_path: Path | None = None,
    ) -> Path:
        """Write skills.lock.json for the given skills under `root`.

        Each skill's sha256 covers its SKILL.md plus payload directory.
        Sources are forward-slash root-relative paths.
        """
        lock_path = lock_path or root / "skills.lock.json"
        root_entries = [
            {"id": ".", "sha256": hash_dir(r, exclude=lock_path)}
            for r in (roots or [root])
        ]
        skills_map: dict[str, dict] = {}
        for skill in skills:
            skill_dir = Path(skill.path).parent if skill.path else root
            skills_map[skill.identity] = {
                "version": str(skill.version),
                "sha256": hash_skill(skill_dir, exclude=lock_path),
                "source": _root_relative(skill_dir, root),
                "dependencies": {
                    dep_id: dep_range.expression
                    for dep_id, dep_range in skill.dependencies.items()
                },
            }
        payload = {
            "lockfileVersion": LOCKFILE_VERSION,
            "generated": datetime.now(timezone.utc).isoformat(),
            "roots": root_entries,
            "skills": skills_map,
        }
        lock_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        return lock_path

    def verify_lockfile(self, root: Path, lock_path: Path | None = None) -> list[str]:
        """Verify skills.lock.json against the current tree. Fail closed.

        Returns a list of drift messages (empty = verified). Any missing
        file, hash mismatch, or schema violation is a drift message.
        """
        lock_path = lock_path or root / "skills.lock.json"
        if not lock_path.is_file():
            return [f"lockfile missing: {lock_path}"]
        try:
            payload = json.loads(lock_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return [f"lockfile unreadable: {exc}"]
        if payload.get("lockfileVersion") != LOCKFILE_VERSION:
            return [f"unsupported lockfileVersion {payload.get('lockfileVersion')!r}"]
        drift: list[str] = []
        for entry in payload.get("roots", []):
            root_dir = root / entry["id"]
            if not root_dir.is_dir():
                drift.append(f"root missing: {entry['id']}")
                continue
            actual = hash_dir(root_dir, exclude=lock_path)
            if actual != entry.get("sha256"):
                drift.append(f"root hash mismatch: {entry['id']}")
        for identity, row in payload.get("skills", {}).items():
            source = row.get("source")
            if not source:
                drift.append(f"skill {identity!r}: missing source")
                continue
            skill_dir = (root / source).resolve()
            if not skill_dir.is_dir():
                drift.append(f"skill {identity!r}: source dir missing {source}")
                continue
            actual = hash_skill(skill_dir, exclude=lock_path)
            if actual != row.get("sha256"):
                drift.append(f"skill {identity!r}: hash mismatch")
        return drift