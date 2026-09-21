# 4.3 Skill Ecosystem — unified build spec (collated 2026-09-16 from 3 SME briefs)
Target: tools/skills/ecosystem/ (7 files), stdlib Python 3.12, Windows, no network.
Build in a j5-harness-rooted session. Acceptance: loader discovers multi-source
roots; composer runs DAG waves; registry resolves semver + lockfile; sandbox runs
workers with capability grants; contract tests validate schemas.

## Module map (implement in this order)
1. `models` (fold into `__init__.py` if small): SkillMeta, Version, VersionRange,
   Contract, LockEntry dataclasses. Identity key = f"{ns}/{name}".casefold().
2. `skill_loader.py`: rglob SKILL.md per root (project>user>bundled, configurable);
   TOML frontmatter via tomllib (never hand-rolled YAML); required keys: namespace,
   name, version, capabilities, dependencies {ns/name: range}, contract
   {inputs,outputs}, self_tests[]. Load-time validation: well-formed, semver-valid,
   deps exist, self_tests pass, no cycles. Record shadowed entries. API:
   load_skill(path)->SkillMeta. (arch-SME)
3. `semver` (fold into `registry.py`): strict 2.0.0; ops ==,>=,<=,>,<,~=(>=x.y,<x.(y+1)),
   ^(>=x.y.z,<next-major); comma=AND; prereleases excluded unless named; NO
   backtracking — fail with conflicting constraint set + introducing skills.
   Conformance unit tests pin behavior. (arch-SME)
4. `registry.py`: index by casefolded ns/name; resolve(all constraints)->max version;
   skills.lock.json {lockfileVersion, generated, roots[{id,sha256}],
   skills{ns/name:{version,sha256,source,dependencies}}}; forward-slash
   root-relative paths; verify sha256 of SKILL.md + payload dir, fail closed.
   (arch-SME)
5. `composition.py`: adjacency dep->dependent; Kahn waves (wave k = deps in waves<k,
   in-wave order sorted for determinism); remainder after exhaustion = cycle, report
   node set; diamonds OK (execute once). (arch-SME + test-SME)
6. `sandbox.py`: POLICY dict {version,self_tests,filesystem{allow_reads,
   allow_writes,deny_reads,deny_patterns},network{enabled False},resources{cpu/wall/
   mem/threads/fds/procs},imports{deny_modules,allow_modules},builtins{exec/eval/
   compile/__import__ off, open restricted},stdio{capture,cap}}. Enforcement:
   Popen(CREATE_NEW_PROCESS_GROUP) in ctypes job object (memory+time limits);
   sys.meta_path import hook; restricted __builtins__ dict; realpath+normcase fs
   gate (reject UNC `\\`, ADS `:`); socket patch; sanitized env allowlist.
   Policy is enforcement, NOT a trust boundary. (security-SME)
7. `contract_test.py`: types str/int/float/bool/list/dict/any/null + required + enum;
   strict (int("42") FAILS; 42.0 FAILS int); load-time schema checks + runtime
   boundary validation (inputs pre-exec, outputs post-exec); load-time
   match/not_match self-tests (execpolicy pattern); escape-attempt matrix (14 cases
   in brief); lockfile drift matrix (7 cases); DAG matrix (8 cases); stdlib unittest,
   tests/ runnable per-file, fixtures in conftest. Partial failure = full rejection
   (fail-closed). Same-wave skills share no mutable state (documented constraint).
   (test-SME)
8. `skill_hub.py`: OpenCode/Hermes integration surface (skill listing, invoke by
   ns/name, wave execution entry point). `__init__.py`: version + re-exports.

## Explicitly accepted gaps (test-SME)
- Coercion edge cases rejected by strictness (documented, intentional).
- Partial contract satisfaction = full rejection (fail-closed).
- No shared mutable state within a wave (design constraint, not test gap).

## Residual risks to carry into review
- Import-hook bypass via introspection (rely on job object + pre-exec review).
- Windows traversal (test `..\..\`, SAM, `\\?\` explicitly).
- semver drift vs packaging norms (conformance tests).
