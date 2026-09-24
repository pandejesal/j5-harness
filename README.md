# J5 Harness

![license](https://img.shields.io/badge/license-PolyForm%20Noncommercial%201.0.0-blue)
![python](https://img.shields.io/badge/python-3.12%2B-green)
![platform](https://img.shields.io/badge/platform-Windows%20%2F%20PowerShell-lightgrey)
![tests](https://img.shields.io/badge/tests-187%20passing-brightgreen)

> **One command center for all your projects.** See everything, delegate anything —
> small tasks go straight to a worker, big tasks fan out across a fleet, and every
> result comes back verified. You plan. The swarm executes.

J5 Harness is a multi-agent coding harness. You describe a task once; J5 picks the
right **domain**, the right **model**, and the right **worker pool** — OpenCode for
quick jobs, Hermes orchestrating fleets of OpenCode / Prime Agent / Kilo sessions
for big ones, Kilo or Prime Agent directly when they fit, Antigravity for visual
work — then verifies the result before calling it done.

## Why J5

- **One place for every project.** Enable/disable projects in config; WSB Alpha,
  Burgonomics, or anything else. No hardcoded paths.
- **Delegate, don't babysit.** `j5 run "backtest a momentum strategy"` — routing,
  dispatch, retries, and verification happen automatically.
- **Free-tier aware.** Models are picked from a health-tracked registry with
  quota-aware fallback chains, per-bucket serialization, circuit breakers, and
  429-aware quarantine. No surprise rate-limit deaths.
- **Trust, but verify.** Every DONE needs git-diff evidence plus a re-run by a
  *different* agent, multi-model cross-checks, and a quality scoreboard.
- **Token-efficient by design.** Skills, MCP servers, response caching, and context
  compression — never pay twice for the same knowledge.

## The three surfaces

| Surface | Launch | Best for |
|---|---|---|
| **CLI** (one-shot) | `j5 status`, `j5 run --prompt "..."` | Scripts, quick checks, automation |
| **TUI** (interactive terminal) | `j5` or `j5 tui` | Living in the terminal, full-screen dashboard |
| **Desktop** (command center) | `j5_desktop\launch-modern.ps1` | Visual control room: composer, metrics, probes, benchmarks |

## Quickstart

**Prerequisites:** Windows 10/11, Python 3.12+, PowerShell 5.1+, `pip install textual PyQt5`.

```powershell
git clone https://github.com/pandejesal/j5-harness.git
cd j5-harness
pip install textual PyQt5 pytest

# one-shot commands (from anywhere, after the PATH step below)
j5 doctor
j5 status
j5 route --project wsb-alpha --task-type coding

# interactive terminal UI (like bare `opencode` / `hermes`)
j5

# delegate a task
j5 run --project wsb-alpha --task-type coding --prompt "Backtest a momentum strategy on NIFTY"

# continue the same worker session later (multi-turn; id printed by any run)
j5 run --project wsb-alpha --task-type coding --session <session-id> --prompt "Now add transaction costs"

# lean dispatch is automatic for short, non-code prompts (no plugins, far fewer
# input tokens); --pure forces it, --no-pure forces full context, J5_PURE=1
# sets the process default
j5 run --project wsb-alpha --task-type coding --prompt "What is the Sharpe ratio formula?"

# review recent turns: model, confidence, tokens, sessions
j5 sessions --limit 20

# mutation boundary: refuse anything that spawns or writes (exit 2)
j5 --readonly status             # allowed (read-only)
j5 --readonly run --prompt "x"   # refused
j5 capabilities                  # the per-command map (JSON with --json)

# desktop command center (no console window, logs to j5_desktop\*.log)
powershell -ExecutionPolicy Bypass -File j5_desktop\launch-modern.ps1
```

**Make `j5` global** (so it works from any `cmd`, like `opencode`):

```batch
mkdir %USERPROFILE%\bin
copy j5.cmd.template %USERPROFILE%\bin\j5.cmd
setx PATH "%PATH%;%USERPROFILE%\bin"
```

then reopen your terminal. (Adapt the `python` path inside `j5.cmd` if yours differs —
see [`j5.cmd.template`](j5.cmd.template).)

## How delegation works

```
you: j5 run "design a mean-reversion strategy"
        │
        ▼
┌───────────────┐   ┌────────────────┐   ┌───────────────────┐
│ domain router │──▶│ free-model     │──▶│ worker pool       │
│ quant/...     │   │ router + health│   │ opencode · hermes │
└───────────────┘   └────────────────┘   │ kilo · prime · agy│
                                         └─────────┬─────────┘
                                                   ▼
                                         ┌───────────────────┐
                                         │ verify: diff +    │
                                         │ foreign re-run +  │
                                         │ scoreboard        │
                                         └───────────────────┘
```

1. **Route** — domain inferred (`quant`, `finance`, `drone`, `research`,
   `coding`, `general`), model picked from EMA-scored fallback chains.
2. **Decompose** — tasks split into a dependency DAG with per-leaf skill bindings.
3. **Dispatch** — serialized per Zen IP bucket; failures fall down the chain,
   breakers trip, quarantines apply.
4. **Verify** — reviewer + critic gates, receipt schema, quality scoreboard.
5. **Record** — everything lands in the per-project ledger.

## Subagents

Specialists live in [`.opencode/agent/`](.opencode/agent/) and plug into any
OpenCode-compatible runner:

| Agent | Role |
|---|---|
| `quant`, `finance`, `drone`, `research`, `coding`, `general` | Domain execution with model pools, skills, tools, fallback ladders |
| `reviewer` | Independent verification gate — never implements, only reviews |
| `critic` | Plan critic — hard stop before execution |
| `subagent-creator` | Generates new subagent profiles from templates |

## Configuration

- [`tools/reliability/reliability.config.json`](tools/reliability/reliability.config.json) —
  enabled projects, directories, fallback ladders, circuit breakers, Kilo bus paths.
- [`domains/domains.config.json`](domains/domains.config.json) — per-domain models,
  skills, tools, data sources, constraints.
- Dormant projects (Safe Sponsor AI, Resonance) stay in config with
  `"enabled": false` — no code changes to toggle them.

## Tests

187 tests green, plus 3 live-backend tests that skip by default:

```powershell
python -m pytest tools/domains/test_domains.py tools/harness/test_integration_contracts.py `
  tools/harness/test_e2e_integration.py tools/skills/ecosystem/contract_test.py `
  tools/router/test_cli_gateway.py -q

# Live tests (real opencode + agy backends, slower):
J5_LIVE=1 python -m pytest tools/harness/test_bridge_hardening.py -v
```

Coverage includes: router/fallback/EMA behavior, delegation DAG + dependency
blocking, skill composition DAGs, semver lockfile drift, 14-case sandbox escape
matrix, Kilo probe round-trips, and per-project breaker isolation.

## Project structure

```
j5.cmd.template      # global `j5` command template for %USERPROFILE%\bin
j5_cli/              # one-shot CLI (j5 status/run/route/probe/...)
j5_tui/              # interactive terminal UI (Textual, curses + ANSI fallbacks)
j5_desktop/          # PyQt5 command center + console-free launcher
.opencode/agent/     # subagent profiles (quant, reviewer, critic, ...)
domains/             # domain system: config, registry, router
skills/              # review-checklist, spec-staleness, test-plan packs
tools/
  router/            # model registry, health tracker, fallback chains, EMA feedback
  delegation/        # orchestrator, DAG, ledger, critique loops, consensus
  skills/ecosystem/  # discovery, composition, registry, sandbox, contracts
  harness/           # integration wiring, Kilo watcher, e2e tests
  reliability/       # MCP reaper, DB health, config
  memory/            # Mnemosyne mirror, shelve/resume runbook
  latency/           # parallel executor, cache, compression, benchmarks
  verification/      # trust-but-verify gates, scoreboard
  ui/                # shared black-theme tokens (CLI/TUI/desktop)
research/            # build specs and phase prep notes
```

## Commercial licensing

J5 is **source-available**, not MIT-style open source. The license is
**PolyForm Noncommercial 1.0.0** ([LICENSE](LICENSE) — the license text controls;
this is just a summary):

- ✅ Free for personal projects, research, education, charities, and government.
- ✅ Read it, fork it, learn from it, contribute noncommercial improvements.
- ❌ Using J5 **commercially** — selling things built with it, running it as a
  service, embedding it in a paid product — requires a separate paid license.

If you make money with this system, the author gets a cut — that's the deal, and
it's written into the license. For a commercial license, contact:
**pandejesal@gmail.com**. Since the author holds 100% of the copyright, terms
can be tailored (startup-friendly, revenue-share, enterprise, buyout).

## Contributing

Noncommercial contributions welcome: fork, branch, open a PR. All contributions
are accepted under the same PolyForm Noncommercial license. Run the test suite
before pushing, and keep new skills contract-tested (`tools/skills/ecosystem/`).

## License

Copyright 2026 Jesal Pande. Licensed under the
[PolyForm Noncommercial License 1.0.0](LICENSE).
Commercial use requires a separate license — see above.
