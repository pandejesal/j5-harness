# J5 Phase-4 prep notes (banked 2026-09-16 — build in a j5-harness-rooted session)

## 4.3 skill ecosystem — SME design briefs (2/3 consultations used)

### A. Capability sandbox (security SME, HIGH confidence)
- Treat as policy-enforcement layer, NOT a trust boundary (pure-Python hooks bypassable).
- Policy-as-data schema: version, self_tests {match[], not_match[]}, filesystem
  {allow_reads[], allow_writes[], deny_reads[], deny_patterns[]}, network {enabled,
  allow_outbound[], allow_inbound}, resources {cpu/wall time, memory_mb, max_threads,
  max_open_files, max_spawned_processes}, imports {deny_modules[], allow_modules[]},
  builtins {__import__/exec/eval/compile off, open restricted}, stdio {capture, cap}.
- Enforcement: subprocess.Popen (CREATE_NEW_PROCESS_GROUP) inside a Win32 Job Object
  via ctypes (memory + job-time limits — strongest control, kernel-enforced);
  sys.meta_path import hook; restricted __builtins__ dict; realpath+normcase
  filesystem gate; socket monkey-patch; env sanitized (explicit allowlist only).
- Load-time self-tests: match[] must succeed, not_match[] must raise
  (PermissionError/ImportError/OSError) — borrowed from Codex execpolicy.
- Top risks: (1) introspection bypass of import hooks — accept, rely on job object +
  pre-execution review; (2) Windows path traversal (UNC/device/ADS) — reject `\\`,
  `:`, normalize with normcase+realpath, test `..\..`, SAM, `\\?\`; (3) resource
  exhaustion — conservative limits + watchdog thread alongside job object.
- Gotchas: `resource` module is Linux-only; job handles must CloseHandle in finally;
  `__builtins__` injected as dict; never system temp (use skill dir).

### B. Composition DAG + registry (architecture SME, HIGH confidence)
- 7 modules: models (SkillMeta/Version/VersionRange/Contract/LockEntry), semver
  (hand-rolled: ==,>=,<=,>,<,~=,^,comma-AND; strict 2.0.0; prereleases excluded
  unless named; NO backtracking — fail with conflicting constraint set), frontmatter
  (TOML via tomllib — NO hand-rolled YAML), discovery (rglob SKILL.md, casefolded
  ns/name keys, precedence project>user>bundled, record shadowed), registry,
  dag (Kahn waves; remainder = cycle report), engine (contract check + waves).
- Lockfile skills.lock.json: version, roots w/ sha256, per-skill version+sha256+
  source+deps; forward-slash root-relative paths; fail closed on hash mismatch
  (hash payload dir, not just SKILL.md).
- Contract types: str/int/float/bool/list/dict/any/null + required + enum;
  validate inputs pre-exec, outputs post-exec; self_tests at load.
- Risks: semver drift vs `packaging` norms (pin with conformance tests); TOML-only
  (fail-closed subset parser if YAML ever mandated); mutable-payload drift (hashing).

## backends/prime — Prime Intellect Prime Agent (repo: PrimeIntellect-ai/prime-agent)
- RLM-native harness (persistent IPython, recursive subagents); began as pi-mono fork.
- Headless integration path: `prime-agent --mode rpc --no-session` (JSON protocol,
  see rpc.md) + JSON mode + TS SDK (`@earendil-works/pi-coding-agent`).
- Session ops: `agents`, `attach`, `--resume`, `status`, `doctor`, `shutdown`.
- Auth: /login (subscription) or API-key env — free-tier fit UNVERIFIED, check first.
- Native skills system — aligns with 4.3 skill-exchange story.
- Adapter shape: mirror antigravity_bridge.py (arg-list, JSON, timeout, regression
  proof); read rpc.md protocol at build time. License check before porting code.

## Session facts to preserve
- VPN/location rotation resets Zen limits (advisory-only, per-bucket modeling).
- Kilo uses its OWN free model — excluded from shared Hermes+OpenCode+OpenChamber key.
- Router endpoints still placeholders (zen.example.com) — need real URLs + probe data.
- Staged state: .swarm-staged/plan.json + spec.md → copy to .swarm/ in rooted session.
