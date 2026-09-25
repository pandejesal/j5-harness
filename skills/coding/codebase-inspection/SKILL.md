---
namespace = "coding"
name = "codebase-inspection"
version = "1.0.0"
capabilities = ["audit", "metrics"]
trigger_patterns = ["review codebase", "analyze repo", "how big is", "tech debt audit"]
applicable_agents = ["reviewer", "planner", "coding"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# coding/codebase-inspection

Eight passes, one report. Quantitative backbone (pygount) plus key-file
reading — LOC alone never concludes anything.

## Trigger

Use when: onboarding to unfamiliar code, pre-work audits, "how big / healthy
is this repo", or tech-debt assessment before planning.

## Passes

1. **Identity** — README/LICENSE/CONTRIBUTING exist? Metadata
   (`package.json`/`pyproject.toml`/`Cargo.toml`): name, version, author,
   license. Entry point per stack.
2. **Structure** — top-level dirs; `src|lib|app` layout; depth-2 arch dirs.
   Flag monolith dirs, missing test dirs, build configs.
3. **LOC (pygount)** — always with `--folders-to-skip` (else it hangs on dep
   trees!): `.git,node_modules,venv,.venv,__pycache__,dist,build,.next,.tox`.
   `--format=summary` default, `--format=json` for machines, `--suffix=` to
   target languages. Read `__duplicate__` (copy-paste debt) and comment ratio
   (<5% under-documented).
4. **Key files** — entry point + orchestrator first 60–100 lines; then per
   type: boot, domain models, data layer, plugin/registry, workers, build
   configs. First 50–80 lines each: hierarchy, ctor deps, patterns.
5. **Dependencies** — versions pinned (flag `"latest"`), lockfile committed
   (flag if gitignored), stale majors, deprecated APIs, top-level counts.
6. **Git health** — last-10 log, total count, last activity date, branches,
   tags. Flag: stale >1yr, single-commit squash, no releases.
7. **Quality** — TODO/FIXME density, >500-line files, lint configs present
   (`.eslintrc`, `ruff.toml`, `tsconfig.strict`), secret patterns
   (`.pem/.key` in repo), input sanitization on plugin surfaces.
8. **Report** — Overview / Code Statistics / Architecture / Observations
   (Strengths + Concerns-Tech-Debt) / Summary with next steps.

## Windows pitfalls

- `pygount.exe` lands under `%APPDATA%\Python\Python3XX\Scripts\` — use full
  path or extend PATH.
- Markdown counts as 0 code lines (all comments) — expected, not a bug.
- JSON counts conservatively — use `wc -l` for true sizes.

## Verify before use

- [ ] Exclusions applied (no dep-tree crawl).
- [ ] Key files actually read, not just listed.
- [ ] Every concern has a file:line or command-output citation.

## Source

Adapted from `evsphereofficial/elevia-skills` ([MIT](https://github.com/evsphereofficial/elevia-skills)):
`github/codebase-inspection.md` v2.0.0. J5 additions: citation requirement,
Windows-first notes, report skeleton tightened.
