"""Strict contract validation + load-time self-tests + unittest matrices.

Types: str, int, float, bool, list, dict, any, null. Strictness is
intentional: int("42") FAILS, 42.0 FAILS int, True FAILS int. Partial
contract satisfaction = full rejection (fail-closed). Same-wave skills
share no mutable state (design constraint). Runnable per-file with
`python -m unittest tools.skills.ecosystem.contract_test`.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from . import Contract, SkillMeta, Version, VersionRange
from .composition import CycleError, compose_waves

VALID_TYPES = ("str", "int", "float", "bool", "list", "dict", "any", "null")


class ContractValidationError(ValueError):
    """Raised when a value violates its contract schema."""


def validate_schema(schema: dict) -> None:
    """Validate a schema dict itself (type name + enum shape)."""
    if not isinstance(schema, dict):
        raise ContractValidationError(f"schema must be a dict, got {type(schema).__name__}")
    type_name = schema.get("type", "any")
    if type_name not in VALID_TYPES:
        raise ContractValidationError(f"unknown type {type_name!r}")
    enum = schema.get("enum")
    if enum is not None and not isinstance(enum, list):
        raise ContractValidationError("enum must be a list")


def validate_value(value, schema: dict) -> None:
    """Validate `value` against a strict schema dict. Raises on violation."""
    validate_schema(schema)
    type_name = schema.get("type", "any")
    if type_name == "any":
        return
    if type_name == "null":
        if value is not None:
            raise ContractValidationError(f"expected null, got {type(value).__name__}")
        return
    if type_name == "str":
        if not isinstance(value, str):
            raise ContractValidationError(f"expected str, got {type(value).__name__}")
    elif type_name == "int":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ContractValidationError(f"expected int, got {type(value).__name__}")
    elif type_name == "float":
        if not isinstance(value, float):
            raise ContractValidationError(f"expected float, got {type(value).__name__}")
    elif type_name == "bool":
        if not isinstance(value, bool):
            raise ContractValidationError(f"expected bool, got {type(value).__name__}")
    elif type_name == "list":
        if not isinstance(value, list):
            raise ContractValidationError(f"expected list, got {type(value).__name__}")
        item_schema = schema.get("items")
        if item_schema is not None:
            for item in value:
                validate_value(item, item_schema)
    elif type_name == "dict":
        if not isinstance(value, dict):
            raise ContractValidationError(f"expected dict, got {type(value).__name__}")
        properties = schema.get("properties", {})
        for key, item_schema in properties.items():
            if key not in value:
                if item_schema.get("required", False):
                    raise ContractValidationError(f"missing required key {key!r}")
                continue
            validate_value(value[key], item_schema)
    enum = schema.get("enum")
    if enum is not None and value not in enum:
        raise ContractValidationError(f"value {value!r} not in enum {enum!r}")


def validate_inputs(contract: Contract, inputs: dict) -> None:
    """Validate inputs pre-exec against the contract inputs schema."""
    for key, schema in contract.inputs.items():
        if key not in inputs:
            raise ContractValidationError(f"missing input {key!r}")
        validate_value(inputs[key], schema)
    for key in inputs:
        if key not in contract.inputs:
            raise ContractValidationError(f"unexpected input {key!r}")


def validate_outputs(contract: Contract, outputs: dict) -> None:
    """Validate outputs post-exec against the contract outputs schema."""
    for key, schema in contract.outputs.items():
        if key not in outputs:
            raise ContractValidationError(f"missing output {key!r}")
        validate_value(outputs[key], schema)
    for key in outputs:
        if key not in contract.outputs:
            raise ContractValidationError(f"unexpected output {key!r}")


def validate_contract(contract: Contract, inputs: dict, outputs: dict) -> None:
    """Validate both directions (inputs pre-exec, outputs post-exec)."""
    validate_inputs(contract, inputs)
    validate_outputs(contract, outputs)


def run_self_tests(meta: SkillMeta, inputs: dict | None = None) -> list[str]:
    """Run load-time match/not_match self-tests. Empty list = pass.

    Each self-test dict carries ``match`` (must validate) and/or
    ``not_match`` (must raise) input maps, per the execpolicy pattern.
    """
    failures: list[str] = []
    base = dict(inputs or {})
    for index, test in enumerate(meta.self_tests):
        label = f"self_test[{index}]"
        if "match" in test:
            candidate = dict(base)
            candidate.update(test["match"])
            try:
                validate_inputs(meta.contract, candidate)
            except ContractValidationError as exc:
                failures.append(f"{label}: match failed: {exc}")
        if "not_match" in test:
            candidate = dict(base)
            candidate.update(test["not_match"])
            try:
                validate_inputs(meta.contract, candidate)
            except ContractValidationError:
                pass
            else:
                failures.append(f"{label}: not_match unexpectedly passed")
    return failures


def _write_skill(
    root: Path,
    namespace: str,
    name: str,
    version: str,
    dependencies: dict[str, str] | None = None,
    capabilities: list[str] | None = None,
    self_tests: list[dict] | None = None,
    payload: str | None = None,
) -> Path:
    """Write a minimal skill directory under `root`; returns SKILL.md path."""
    skill_dir = root / namespace / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f'namespace = "{namespace}"',
        f'name = "{name}"',
        f'version = "{version}"',
        "capabilities = []",
        "dependencies = {}",
        "contract = { inputs = {}, outputs = {} }",
        "self_tests = []",
    ]
    if capabilities:
        caps = ", ".join(f'"{c}"' for c in capabilities)
        lines[4] = f"capabilities = [{caps}]"
    if dependencies:
        dep_lines = ", ".join(f'"{key}" = "{expr}"' for key, expr in dependencies.items())
        lines[5] = f"dependencies = {{ {dep_lines} }}"
    if self_tests:
        test_lines: list[str] = []
        for test in self_tests:
            parts: list[str] = []
            if "match" in test:
                inner = ", ".join(f"{key} = {value!r}" for key, value in test["match"].items())
                parts.append(f"match = {{ {inner} }}")
            if "not_match" in test:
                inner = ", ".join(f"{key} = {value!r}" for key, value in test["not_match"].items())
                parts.append(f"not_match = {{ {inner} }}")
            test_lines.append("{ " + ", ".join(parts) + " }")
        lines[7] = "self_tests = [" + ", ".join(test_lines) + "]"
    lines.append("---")
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if payload is not None:
        payload_dir = skill_dir / "payload"
        payload_dir.mkdir(exist_ok=True)
        (payload_dir / "main.py").write_text(payload, encoding="utf-8")
    return skill_md


class StrictValidatorTest(unittest.TestCase):
    """Strict type identity: no coercion, no bool-as-int, no int-as-float."""

    def test_int_rejects_string(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value("42", {"type": "int"})

    def test_int_rejects_float(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value(42.0, {"type": "int"})

    def test_int_rejects_bool(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value(True, {"type": "int"})

    def test_str_accepts_string(self) -> None:
        validate_value("hello", {"type": "str"})

    def test_float_rejects_int(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value(42, {"type": "float"})

    def test_bool_rejects_int(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value(1, {"type": "bool"})

    def test_null(self) -> None:
        validate_value(None, {"type": "null"})
        with self.assertRaises(ContractValidationError):
            validate_value(0, {"type": "null"})

    def test_any(self) -> None:
        validate_value(object(), {"type": "any"})

    def test_enum(self) -> None:
        validate_value("a", {"type": "str", "enum": ["a", "b"]})
        with self.assertRaises(ContractValidationError):
            validate_value("c", {"type": "str", "enum": ["a", "b"]})

    def test_list_items(self) -> None:
        validate_value([1, 2], {"type": "list", "items": {"type": "int"}})
        with self.assertRaises(ContractValidationError):
            validate_value([1, "x"], {"type": "list", "items": {"type": "int"}})

    def test_dict_required(self) -> None:
        schema = {"type": "dict", "properties": {"x": {"type": "int", "required": True}}}
        validate_value({"x": 1}, schema)
        with self.assertRaises(ContractValidationError):
            validate_value({}, schema)

    def test_unknown_type(self) -> None:
        with self.assertRaises(ContractValidationError):
            validate_value(1, {"type": "nope"})


class SelfTestRunnerTest(unittest.TestCase):
    """match must succeed, not_match must raise (execpolicy pattern)."""

    def _meta(self, self_tests: list[dict]) -> SkillMeta:
        return SkillMeta(
            namespace="test",
            name="demo",
            version=Version.parse("1.0.0"),
            contract=Contract(inputs={"x": {"type": "int"}}),
            self_tests=tuple(self_tests),
        )

    def test_match_passes(self) -> None:
        self.assertEqual(run_self_tests(self._meta([{"match": {"x": 1}}])), [])

    def test_not_match_raises(self) -> None:
        self.assertEqual(run_self_tests(self._meta([{"not_match": {"x": "bad"}}])), [])

    def test_match_failure_reported(self) -> None:
        failures = run_self_tests(self._meta([{"match": {"x": "bad"}}]))
        self.assertEqual(len(failures), 1)
        self.assertIn("match failed", failures[0])

    def test_not_match_passing_reported(self) -> None:
        failures = run_self_tests(self._meta([{"not_match": {"x": 1}}]))
        self.assertEqual(len(failures), 1)
        self.assertIn("unexpectedly passed", failures[0])


class EscapeMatrixTest(unittest.TestCase):
    """14 structural escape attempts must all be rejected (fail-closed)."""

    CASES: list[tuple[str, str]] = [
        ("parent traversal (posix)", "../../../etc/passwd"),
        ("parent traversal (windows)", r"..\..\..\windows\system32\cmd.exe"),
        ("UNC share", r"\\server\share\file.txt"),
        ("extended-length device path", r"\\?\C:\Windows\System32\cmd.exe"),
        ("device namespace", r"\\.\C:\Windows\System32\cmd.exe"),
        ("absolute outside allowlist", r"C:\Windows\System32\cmd.exe"),
        ("SAM database", r"C:\Windows\System32\config\SAM"),
        ("alternate data stream", r"file.txt:stream"),
        ("ADS on absolute path", r"C:\Windows\System32\cmd.exe:stream"),
        ("ADS data stream", r"C:\Windows\System32\cmd.exe::$DATA"),
        ("triple-dot trick", r"...\windows\system32\cmd.exe"),
        ("embedded traversal", r"C:\Windows\System32\..\..\Windows\System32\cmd.exe"),
        ("trailing space", r"C:\Windows\System32\cmd.exe "),
        ("trailing dot", r"C:\Windows\System32\cmd.exe."),
    ]

    def setUp(self) -> None:
        from . import sandbox as _sandbox  # lazy: sandbox imports after contract_test

        self.sandbox = _sandbox
        self.policy = {
            "filesystem": {
                "allow_reads": [str(Path.cwd())],
                "allow_writes": [],
                "deny_reads": [],
                "deny_patterns": [],
            }
        }

    def test_all_escape_attempts_rejected(self) -> None:
        for label, attempt in self.CASES:
            with self.subTest(label=label, attempt=attempt):
                with self.assertRaises(PermissionError):
                    self.sandbox.check_path(attempt, self.policy, "read")

    def test_windows_shapes_rejected_off_windows(self) -> None:
        # Per-OS contract: on POSIX hosts, Windows drive-letter shapes can
        # never be legitimate skill paths, so reject_reasons() refuses them
        # structurally (absolute-system, ADS payloads, trailing dot/space).
        # On Windows itself these fall through to the allowlist check
        # (covered by the matrix test above), so this unit test only runs
        # off Windows.
        if os.name == "nt":
            self.skipTest("Windows host: covered by the allowlist matrix")
        shapes = [
            r"C:\Windows\System32\cmd.exe",
            r"C:\Windows\System32\config\SAM",
            r"C:\Windows\System32\cmd.exe:stream",
            r"C:\Windows\System32\cmd.exe::$DATA",
            r"C:\Windows\System32\cmd.exe ",
            r"C:\Windows\System32\cmd.exe.",
            r"C:/Windows/System32/cmd.exe",
        ]
        for shape in shapes:
            with self.subTest(shape=shape):
                reason = self.sandbox.reject_reasons(shape)
                self.assertIsNotNone(reason)
                self.assertIn("Windows", reason)


class DagMatrixTest(unittest.TestCase):
    """8 DAG cases: waves, determinism, diamonds-once, cycles."""

    def _skill(self, identity: str, deps: dict[str, str] | None = None) -> SkillMeta:
        namespace, name = identity.split("/", 1)
        return SkillMeta(
            namespace=namespace,
            name=name,
            version=Version.parse("1.0.0"),
            dependencies={dep: VersionRange(expr) for dep, expr in (deps or {}).items()},
        )

    def _waves(self, skills: list[SkillMeta]) -> list[list[str]]:
        return [[s.identity for s in wave] for wave in compose_waves(skills)]

    def test_single_skill(self) -> None:
        self.assertEqual(self._waves([self._skill("a/x")]), [["a/x"]])

    def test_linear_chain(self) -> None:
        skills = [
            self._skill("a/c", {"a/b": ">=1.0.0"}),
            self._skill("a/b"),
        ]
        self.assertEqual(self._waves(skills), [["a/b"], ["a/c"]])

    def test_diamond_executes_once(self) -> None:
        skills = [
            self._skill("a/d", {"a/b": ">=1.0.0", "a/c": ">=1.0.0"}),
            self._skill("a/c", {"a/b": ">=1.0.0"}),
            self._skill("a/b"),
        ]
        waves = self._waves(skills)
        flat = [identity for wave in waves for identity in wave]
        self.assertEqual(flat.count("a/b"), 1)
        self.assertEqual(waves, [["a/b"], ["a/c"], ["a/d"]])

    def test_in_wave_sorted_deterministic(self) -> None:
        skills = [self._skill("a/z"), self._skill("a/a"), self._skill("a/m")]
        self.assertEqual(self._waves(skills), [["a/a", "a/m", "a/z"]])

    def test_two_independent_waves(self) -> None:
        skills = [
            self._skill("a/b", {"a/a": ">=1.0.0"}),
            self._skill("a/a"),
            self._skill("a/d", {"a/c": ">=1.0.0"}),
            self._skill("a/c"),
        ]
        self.assertEqual(self._waves(skills), [["a/a", "a/c"], ["a/b", "a/d"]])

    def test_self_cycle(self) -> None:
        skills = [self._skill("a/x", {"a/x": ">=1.0.0"})]
        with self.assertRaises(CycleError) as ctx:
            compose_waves(skills)
        self.assertIn("a/x", ctx.exception.cycle_nodes)

    def test_two_node_cycle(self) -> None:
        skills = [
            self._skill("a/x", {"a/y": ">=1.0.0"}),
            self._skill("a/y", {"a/x": ">=1.0.0"}),
        ]
        with self.assertRaises(CycleError) as ctx:
            compose_waves(skills)
        self.assertEqual(ctx.exception.cycle_nodes, frozenset({"a/x", "a/y"}))

    def test_missing_dependency(self) -> None:
        skills = [self._skill("a/x", {"a/ghost": ">=1.0.0"})]
        with self.assertRaises(ValueError):
            compose_waves(skills)


class LockfileMatrixTest(unittest.TestCase):
    """7 lockfile drift cases: every mutation must be detected (fail-closed)."""

    def setUp(self) -> None:
        from . import registry as _registry  # lazy: registry imports after contract_test
        from .skill_loader import load_skill  # lazy: skill_loader imports contract_test

        self.registry = _registry
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skill_md = _write_skill(
            self.root,
            "test",
            "demo",
            "1.0.0",
            payload="def run(inputs, context=None):\n    return {}\n",
        )
        self.skill = load_skill(self.skill_md, source="project")
        self.lock_path = self.registry.Registry().write_lockfile(
            self.root, [self.skill], roots=[self.root], lock_path=self.root / "skills.lock.json"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _verify(self) -> list[str]:
        return self.registry.Registry().verify_lockfile(self.root, lock_path=self.lock_path)

    def test_clean_lockfile(self) -> None:
        self.assertEqual(self._verify(), [])

    def test_missing_lockfile(self) -> None:
        self.lock_path.unlink()
        drift = self._verify()
        self.assertEqual(len(drift), 1)
        self.assertIn("missing", drift[0])

    def test_skill_payload_tampered(self) -> None:
        payload = self.root / "test" / "demo" / "payload" / "main.py"
        payload.write_text("def run(inputs, context=None):\n    return {'x': 1}\n", encoding="utf-8")
        drift = self._verify()
        self.assertTrue(any("hash mismatch" in message for message in drift))

    def test_skill_md_tampered(self) -> None:
        skill_md = self.root / "test" / "demo" / "SKILL.md"
        skill_md.write_text(skill_md.read_text(encoding="utf-8") + "\n# extra\n", encoding="utf-8")
        drift = self._verify()
        self.assertTrue(any("hash mismatch" in message for message in drift))

    def test_skill_source_missing(self) -> None:
        import shutil

        shutil.rmtree(self.root / "test" / "demo")
        drift = self._verify()
        self.assertTrue(any("source dir missing" in message for message in drift))

    def test_lockfile_version_unsupported(self) -> None:
        import json

        payload = json.loads(self.lock_path.read_text(encoding="utf-8"))
        payload["lockfileVersion"] = 999
        self.lock_path.write_text(json.dumps(payload), encoding="utf-8")
        drift = self._verify()
        self.assertTrue(any("lockfileVersion" in message for message in drift))

    def test_root_hash_mismatch(self) -> None:
        (self.root / "extra.txt").write_text("x", encoding="utf-8")
        drift = self._verify()
        self.assertTrue(any("root hash mismatch" in message for message in drift))


if __name__ == "__main__":
    unittest.main()