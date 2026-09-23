#!/usr/bin/env python3
"""
J5 Harness CLI — Multi-domain coding harness for quant, finance, drone, research, coding, general.

Commands:
  j5 run        — Execute a task with domain-aware routing
  j5 route      — Show routing decision for a task
  j5 status     — Show harness status (health, scores, projects)
  j5 projects   — List/manage projects
  j5 domains    — List/manage domains
  j5 skills     — List/manage skills
  j5 probe      — Run Kilo probe round-trip
  j5 watch      — Start Kilo watcher
  j5 config     — Show/edit configuration
  j5 benchmark  — Run latency benchmarks
  j5 doctor     — Health check and diagnostics
"""

from __future__ import annotations

import argparse
import json
import sys
import os
from pathlib import Path
from typing import Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles for Unicode marks (✓, ✗, ─)
if sys.platform == "win32":
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


from tools.domains import (
    DomainRegistry,
    ProjectRegistry,
    DomainAwareRouter,
    MultiProjectRouter,
    load_project_config,
    list_available_domains,
    list_projects,
)
from tools.router import FreeModelRouter, HealthTracker, FeedbackLoop, FallbackChainBuilder
from tools.harness.integration import (
    load_config,
    build_project_contexts,
    build_project_states,
    make_router_fn,
    run_probe_roundtrip,
    get_shared,
)
from tools.latency.benchmark import run_benchmark, BenchmarkConfig
from tools.latency.parallel_executor import run_parallel
from tools.latency.caching import MultiTierCache, CacheConfig
from tools.latency.context_compression import compress_context, CompressionConfig
from tools.latency.speculative import speculate, SpeculativeConfig
from tools.latency.async_engine import AsyncEngine, AsyncConfig
from tools.delegation.orchestrator import Orchestrator
from tools.delegation.multi_model_consensus import run_consensus
from tools.delegation.critique_loop import CritiqueLoop
from tools.delegation.ledger import DelegationLedger
from tools.skills.ecosystem import SkillHub, discover_skills
from tools.ui.theme import (
    ANSI,
    color,
    fail_line,
    hint,
    ok_line,
    separator,
    supports_color,
    title,
)


# ---------------------------------------------------------------------------
# Mutation boundary: capability map + readonly guard
#
# Single source of truth for what each command is allowed to do. Readonly
# mode (--readonly flag or J5_READONLY=1 env) refuses any command with any
# True capability and exits 2. `capabilities` itself is read-only so the
# boundary stays inspectable while locked.
# ---------------------------------------------------------------------------

COMMAND_CAPABILITIES: dict[str, dict[str, bool]] = {
    "run":          {"spawns_worker": True,  "mutates_project": True,  "mutates_harness_state": True},
    "probe":        {"spawns_worker": True,  "mutates_project": True,  "mutates_harness_state": True},
    "watch":        {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": True},
    "route":        {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "status":       {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "projects":     {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "domains":      {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "skills":       {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "config":       {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "benchmark":    {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "sessions":    {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "doctor":      {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "capabilities": {"spawns_worker": False, "mutates_project": False, "mutates_harness_state": False},
    "tui":          {"spawns_worker": True,  "mutates_project": True,  "mutates_harness_state": True},
}

READONLY_EXIT_CODE = 2

_CAPABILITY_REASONS = {
    "spawns_worker": "spawn worker processes",
    "mutates_project": "write into project directories",
    "mutates_harness_state": "write harness state (ledger/cache/tracker)",
}


def readonly_source(args: argparse.Namespace) -> str:
    """Return how readonly mode was enabled, or '' when it is off."""
    if getattr(args, "readonly", False):
        return "--readonly"
    if os.environ.get("J5_READONLY", "").strip().lower() in ("1", "true", "yes"):
        return "J5_READONLY=1"
    return ""


def cmd_route(args: argparse.Namespace) -> int:
    """Show routing decision for a task."""
    project = args.project or "wsb-alpha"
    task_type = args.task_type or "coding"
    
    router = MultiProjectRouter()
    decision = router.pick(project, task_type)
    
    output = {
        "project": decision.project,
        "domain": decision.domain,
        "task_type": decision.task_type,
        "model": decision.model,
        "endpoint": decision.endpoint,
        "expected_latency_ms": decision.expected_latency_ms,
        "reason": decision.reason,
        "chain": decision.chain,
    }
    
    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{color('Project:', ANSI.ACCENT)} {output['project']}")
        print(f"{color('Domain: ', ANSI.ACCENT)} {output['domain']}")
        print(f"{color('Task:   ', ANSI.ACCENT)} {output['task_type']}")
        print(f"{color('Model:  ', ANSI.ACCENT)} {output['model']}")
        print(f"{color('Endpoint:', ANSI.ACCENT)} {output['endpoint']}")
        print(f"{color('Latency:', ANSI.ACCENT)} {output['expected_latency_ms']:.1f}ms")
        print(f"{color('Reason: ', ANSI.ACCENT)} {output['reason']}")
        print(f"{color('Chain:  ', ANSI.ACCENT)} {' -> '.join(output['chain'])}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show harness status."""
    router = MultiProjectRouter()
    status = router.global_status()
    
    if args.json:
        print(json.dumps(status, indent=2, default=str))
    else:
        print(title("=== J5 Harness Status ==="))
        print(f"{color('Projects:', ANSI.ACCENT)} {list(status['projects'].keys())}")
        for name, proj_status in status['projects'].items():
            print(f"\n  {color(name, ANSI.ACCENT)} ({proj_status['domain']}):")
            print(f"    {color('In-flight:', ANSI.ACCENT)} {proj_status['in_flight']}/{proj_status['max_in_flight']}")
            print(f"    {color('Quarantined:', ANSI.ACCENT)} {proj_status['quarantined']}")
        print(f"\n{color('Shared Health:', ANSI.ACCENT)} {len(status['shared_health'])} models tracked")
        print(f"{color('Shared Scores:', ANSI.ACCENT)} {len(status['shared_scores'])} models scored")
    return 0


def cmd_projects(args: argparse.Namespace) -> int:
    """List/manage projects."""
    registry = ProjectRegistry()
    projects = registry.list_projects()
    
    if args.json:
        output = []
        for p in projects:
            proj = registry.get_project(p)
            output.append({
                "name": proj.name,
                "domain": proj.domain,
                "enabled": proj.enabled,
                "dir": proj.project_dir,
                "fallback_ladders": proj.custom_fallback_ladders,
            })
        print(json.dumps(output, indent=2))
    else:
        print(title("=== Projects ==="))
        for p in projects:
            proj = registry.get_project(p)
            status = "enabled" if proj.enabled else "disabled"
            status_colored = color(status, ANSI.SUCCESS) if proj.enabled else color(status, ANSI.ERROR)
            print(f"  {color(p, ANSI.ACCENT)} [{proj.domain}] ({status_colored})")
            print(f"    {color('Dir:', ANSI.ACCENT)} {proj.project_dir}")
            for role, ladder in proj.custom_fallback_ladders.items():
                print(f"    {color(role + ':', ANSI.ACCENT)} {' -> '.join(ladder)}")
    return 0


def cmd_domains(args: argparse.Namespace) -> int:
    """List/manage domains."""
    registry = DomainRegistry()
    domains = registry.list_domains()
    
    if args.json:
        output = []
        for d in domains:
            dom = registry.get_domain(d)
            output.append({
                "name": dom.name,
                "description": dom.description,
                "models": {"primary": dom.models.primary, "fallback": dom.models.fallback},
                "skills": dom.skills,
                "tools": dom.tools,
                "data_sources": dom.data_sources,
                "constraints": dom.constraints.__dict__,
                "fallback_ladders": dom.fallback_ladders,
            })
        print(json.dumps(output, indent=2))
    else:
        print(title("=== Domains ==="))
        for d in domains:
            dom = registry.get_domain(d)
            print(f"  {color(d, ANSI.ACCENT)}: {dom.description}")
            print(f"    {color('Models:', ANSI.ACCENT)} {', '.join(dom.models.primary)} + {', '.join(dom.models.fallback)}")
            print(f"    {color('Skills:', ANSI.ACCENT)} {len(dom.skills)} | {color('Tools:', ANSI.ACCENT)} {len(dom.tools)} | {color('Data:', ANSI.ACCENT)} {len(dom.data_sources)}")
    return 0


def cmd_skills(args: argparse.Namespace) -> int:
    """List/manage skills."""
    project = args.project or "wsb-alpha"
    proj = load_project_config(project)
    hub = SkillHub(roots=[Path(r) for r in proj.get_all_skills()])
    
    skills = hub.list_skills()
    
    if args.json:
        output = [{"identity": s.identity, "version": str(s.version), "source": s.source} for s in skills]
        print(json.dumps(output, indent=2))
    else:
        print(title(f"=== Skills for {project} ({proj.domain}) ==="))
        for s in skills:
            print(f"  {color(s.identity, ANSI.ACCENT)} v{s.version} [{s.source}]")
            print(f"    {color('Capabilities:', ANSI.ACCENT)} {', '.join(s.capabilities)}")
            print(f"    {color('Deps:', ANSI.ACCENT)} {', '.join(s.dependencies.keys()) if s.dependencies else 'none'}")
    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Run Kilo probe round-trip."""
    project = args.project or "wsb-alpha"
    probe_id = args.probe_id or "probe-001"
    prompt = args.prompt or "Test probe from J5 Harness"
    
    proj = load_project_config(project)
    config = load_config()
    kilo_cfg = config.get("kilo", {})
    
    if not kilo_cfg:
        print(fail_line("Error: kilo section not found in config", enabled=supports_color(sys.stderr)), file=sys.stderr)
        return 1
    
    contexts = build_project_contexts(config, "coder")
    ctx = next((c for c in contexts if c.name == project), contexts[0] if contexts else None)
    if ctx is None:
        print(fail_line(f"Error: no project context found for {project}", enabled=supports_color(sys.stderr)), file=sys.stderr)
        return 1
    result = run_probe_roundtrip(ctx, probe_id, prompt, kilo_cfg)
    
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status_ok = result.get('confidence', 0) > 0
        status_text = "SUCCESS" if status_ok else "FAILED"
        status_colored = color(status_text, ANSI.SUCCESS) if status_ok else color(status_text, ANSI.ERROR)
        print(f"{color('Probe:', ANSI.ACCENT)} {probe_id}")
        print(f"{color('Status:', ANSI.ACCENT)} {status_colored}")
        print(f"{color('Model:', ANSI.ACCENT)} {result.get('model_id')}")
        print(f"{color('Output:', ANSI.ACCENT)} {result.get('text', '')[:200]}...")
        if result.get('error'):
            print(fail_line(f"Error: {result['error']}"))
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Start Kilo watcher."""
    # Lazy import: tools.harness.watch_kilo must not be touched by commands
    # that never watch (its import used to create the tracker dir).
    from tools.harness.watch_kilo import process_once as watch_once
    print(hint("Starting Kilo watcher..."))
    print(hint("Press Ctrl+C to stop"))
    try:
        while True:
            watch_once()
            import time
            time.sleep(args.interval or 30)
    except KeyboardInterrupt:
        print(f"\n{ok_line('Watcher stopped')}")
    return 0


def cmd_config(args: argparse.Namespace) -> int:
    """Show/edit configuration."""
    config = load_config()
    
    if args.show or args.json:
        print(json.dumps(config, indent=2))
    return 0


def cmd_benchmark(args: argparse.Namespace) -> int:
    """Run latency benchmarks."""
    print(hint("Running J5 Harness benchmarks..."))
    
    # Benchmark parallel executor
    def dummy_task(x):
        import time
        time.sleep(0.001)
        return x * 2
    
    bench = run_benchmark(
        lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
        BenchmarkConfig(iterations=10, warmup=2),
        "parallel_executor_100_tasks"
    )
    
    # Benchmark cache
    cache = MultiTierCache(CacheConfig(l1_max_entries=10000, enable_l2=False))
    for i in range(1000):
        cache.set(f"key{i}", f"value{i}")
    
    bench2 = run_benchmark(
        lambda: [cache.get(f"key{i}") for i in range(100)],
        BenchmarkConfig(iterations=50, warmup=5),
        "cache_get_100_keys"
    )
    
    # Benchmark compression
    long_text = "This is a test prompt. " * 500
    bench3 = run_benchmark(
        lambda: compress_context(long_text, CompressionConfig(target_tokens=1000)),
        BenchmarkConfig(iterations=20, warmup=3),
        "context_compression"
    )
    
    results = {
        "parallel_executor": bench.to_dict(),
        "cache": bench2.to_dict(),
        "compression": bench3.to_dict(),
    }
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for name, result in results.items():
            print(f"\n{color(name + ':', ANSI.ACCENT)}")
            print(f"  {color('p50:', ANSI.ACCENT)} {result['latency_ms']['p50']:.2f}ms")
            print(f"  {color('p95:', ANSI.ACCENT)} {result['latency_ms']['p95']:.2f}ms")
            print(f"  {color('p99:', ANSI.ACCENT)} {result['latency_ms']['p99']:.2f}ms")
            print(f"  {color('Throughput:', ANSI.ACCENT)} {result['throughput_per_s']:.1f}/s")
            print(f"  {color('Error rate:', ANSI.ACCENT)} {result['error_rate']:.2%}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Health check and diagnostics."""
    print(title("=== J5 Harness Doctor ==="))
    print()
    
    # Check config
    config = load_config()
    print(ok_line("Config loaded"))
    print(f"  Projects: {list(config.get('projects', {}).keys())}")
    print(f"  Domains: {list(config.get('projects', {}).keys())}")
    
    # Check domains
    registry = DomainRegistry()
    print(ok_line(f"Domains loaded: {registry.list_domains()}"))
    print(separator())
    
    # Check projects
    proj_registry = ProjectRegistry()
    print(ok_line(f"Projects: {proj_registry.list_projects()}"))
    print(separator())
    
    # Check router
    router = MultiProjectRouter()
    status = router.global_status()
    print(ok_line(f"Router: {len(status['projects'])} projects active"))
    print(separator())
    
    # Check skills
    for p in proj_registry.list_projects():
        proj = proj_registry.get_project(p)
        hub = SkillHub(roots=[Path(r) for r in proj.get_all_skills()])
        skills = hub.list_skills()
        print(f"  {p}: {len(skills)} skills")
    print(separator())
    
    # Check Kilo config
    kilo_cfg = config.get("kilo", {})
    if kilo_cfg:
        print(ok_line(f"Kilo config: inbox={kilo_cfg.get('inbox')}"))
    else:
        print(color("[WARN] Kilo config not found", ANSI.WARNING))
    
    print(f"\n{title('=== All checks passed ===')}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Execute a task with domain-aware routing — real dispatch, real answer."""
    import time

    project = args.project or "wsb-alpha"
    task_type = args.task_type or "coding"
    prompt = args.prompt or ""

    if not prompt:
        print(fail_line("Error: --prompt required", enabled=supports_color(sys.stderr)), file=sys.stderr)
        return 1

    config = load_config()
    contexts = {c.name: c for c in build_project_contexts(config, "coder")}
    if project not in contexts:
        print(fail_line(f"Error: unknown project {project!r} (see reliability.config.json projects.*)",
                        enabled=supports_color(sys.stderr)), file=sys.stderr)
        return 1
    ctx = contexts[project]

    task_id = f"task-{int(time.time()) % 100000:05d}"
    session_id = args.session or None
    from tools.router.cli_gateway import resolve_pure
    pure, pure_why = resolve_pure(args.pure, prompt)
    ledger = DelegationLedger(ctx.ledger_path)
    shared = get_shared()
    router_fn = make_router_fn(ctx, shared, config)
    orch = Orchestrator(ledger=ledger, router_fn=router_fn)

    if not args.json:
        print(f"{color('Dispatching:', ANSI.ACCENT)} {task_id} -> {project} [{task_type}]")
        print(f"{color('Gateway:', ANSI.ACCENT)} {type(shared.adapter).__name__}")
        if session_id:
            print(f"{color('Session:', ANSI.ACCENT)} continuing {session_id}")
        print(f"{color('Mode:', ANSI.ACCENT)} "
              f"{'pure (lean, no plugins)' if pure else 'full context'} [{pure_why}]")

    dag = orch.decompose(prompt, [{"task_id": task_id, "prompt": prompt}])
    dag = orch.run(dag, task_type=task_type, session_id=session_id, pure=pure)
    node = dag.nodes[task_id]

    usage = getattr(node, "usage", None) or {}
    result = {
        "task_id": task_id,
        "project": project,
        "task_type": task_type,
        "state": node.state.name,
        "model_id": node.model_id,
        "confidence": float(node.confidence or 0.0),
        "text": node.result or "",
        "session_id": getattr(node, "session_id", None),
        "usage": usage,
        "ledger": str(ctx.ledger_path),
    }
    if node.state.name != "SUCCEEDED":
        result["error"] = getattr(node, "error", None) or "dispatch did not succeed (see ledger)"

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        mark = ok_line if node.state.name == "SUCCEEDED" else fail_line
        print(mark(f"{task_id} {node.state.name} via {node.model_id} "
                   f"(confidence {result['confidence']:.2f})"))
        print(separator())
        print(result["text"] or "(empty response)")
        print(separator())
        tok = usage.get("tokens_total")
        if tok is not None:
            print(hint(f"Tokens: {usage.get('tokens_input', '?')}/{usage.get('tokens_output', '?')} "
                       f"in/out of {tok} total · cost {usage.get('cost', 0)}"))
        if result["session_id"]:
            print(hint(f"Session: {result['session_id']} (re-run with --session to continue)"))
        print(hint(f"Ledger: {result['ledger']}"))

    return 0 if node.state.name == "SUCCEEDED" else 1


def cmd_sessions(args: argparse.Namespace) -> int:
    """List recent worker turns (tasks, models, sessions, usage) per project."""
    limit = max(1, args.limit or 20)
    only = args.project or None
    config = load_config()

    rows: list[dict] = []
    for ctx in build_project_contexts(config, "coder"):
        if only and ctx.name != only:
            continue
        try:
            lines = ctx.ledger_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "result":
                continue
            payload = entry.get("payload") or {}
            usage = payload.get("usage") or {}
            rows.append({
                "project": ctx.name,
                "task_id": entry.get("task_id", "-"),
                "model_id": payload.get("model_id", "-"),
                "confidence": payload.get("confidence", 0.0),
                "session_id": payload.get("session_id") or "-",
                "tokens": usage.get("tokens_total", "-"),
                "ts": entry.get("ts", 0),
            })
    rows.sort(key=lambda r: r["ts"])
    rows = rows[-limit:]

    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    print(f"{'project':<12} {'task':<10} {'model':<28} {'conf':<5} {'tokens':<8} session")
    print("-" * 100)
    for r in rows:
        print(f"{r['project']:<12} {r['task_id']:<10} {str(r['model_id']):<28} "
              f"{float(r['confidence'] or 0.0):<5.2f} {str(r['tokens']):<8} {r['session_id']}")
    if not rows:
        print(hint("No completed turns recorded yet — run `j5 run --prompt ...` first."))
    return 0


def build_parser() -> argparse.ArgumentParser:
    json_sub = argparse.ArgumentParser(add_help=False)
    json_sub.add_argument("--json", action="store_true", dest="sub_json", help="Output JSON")
    # Same dest as the root flag: accepted before AND after the subcommand
    # (`j5 --readonly status` and `j5 status --readonly` both work).
    # default=SUPPRESS is load-bearing: a plain False default on the
    # subparser would overwrite a True set by the root flag (subparsers
    # re-seed their own defaults into the shared namespace). SUPPRESS means
    # the subparser only ever writes when the flag is actually passed.
    json_sub.add_argument("--readonly", action="store_true", default=argparse.SUPPRESS,
                          help="Refuse mutating commands (exit 2)")

    parser = argparse.ArgumentParser(
        prog="j5",
        description="J5 Harness — Multi-domain coding harness for quant, finance, drone, research, coding, general",
        epilog="Readonly mode: --readonly (or J5_READONLY=1) refuses any command that spawns\n"
               "workers or writes anything (run/probe/watch/tui) and exits 2.\n"
               "See `j5 capabilities` for the per-command boundary map.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="J5 Harness 1.0.0")
    parser.add_argument("--json", action="store_true", dest="global_json", help="Output JSON")
    parser.add_argument("--readonly", action="store_true",
                        help="Refuse mutating commands (exit 2). Same as J5_READONLY=1.")
    
    # No subcommand => interactive TUI (like bare `opencode` / `hermes`).
    sub = parser.add_subparsers(dest="command", required=False)
    
    # route
    p = sub.add_parser("route", parents=[json_sub], help="Show routing decision")
    p.add_argument("--project", default="wsb-alpha", help="Project name")
    p.add_argument("--task-type", default="coding", choices=["coding", "research", "analysis", "conversation"])
    
    # status
    sub.add_parser("status", parents=[json_sub], help="Show harness status")
    
    # projects
    sub.add_parser("projects", parents=[json_sub], help="List projects")
    
    # domains
    sub.add_parser("domains", parents=[json_sub], help="List domains")
    
    # skills
    p = sub.add_parser("skills", parents=[json_sub], help="List skills")
    p.add_argument("--project", default="wsb-alpha", help="Project name")
    
    # probe
    p = sub.add_parser("probe", parents=[json_sub], help="Run Kilo probe round-trip")
    p.add_argument("--project", default="wsb-alpha", help="Project name")
    p.add_argument("--probe-id", help="Probe ID")
    p.add_argument("--prompt", help="Prompt to send")
    
    # watch
    p = sub.add_parser("watch", parents=[json_sub], help="Start Kilo watcher")
    p.add_argument("--interval", type=int, default=30, help="Poll interval seconds")
    
    # config
    p = sub.add_parser("config", parents=[json_sub], help="Show configuration")
    p.add_argument("--show", action="store_true", help="Show config")
    
    # benchmark
    sub.add_parser("benchmark", parents=[json_sub], help="Run latency benchmarks")

    # sessions
    p = sub.add_parser("sessions", parents=[json_sub], help="List recent worker turns and sessions")
    p.add_argument("--project", default=None, help="Only this project")
    p.add_argument("--limit", type=int, default=20, help="Max rows to show")
    
    # doctor
    sub.add_parser("doctor", parents=[json_sub], help="Health check and diagnostics")
    
    # run
    p = sub.add_parser("run", parents=[json_sub], help="Execute a task")
    p.add_argument("--project", default="wsb-alpha", help="Project name")
    p.add_argument("--task-type", default="coding", choices=["coding", "research", "analysis", "conversation"])
    p.add_argument("--prompt", required=True, help="Prompt to execute")
    p.add_argument("--session", default=None,
                   help="Continue an existing worker session (id printed by a prior run)")
    p.add_argument("--pure", dest="pure", action="store_true", default=None,
                   help="Lean dispatch: no external plugins (simple Q&A)")
    p.add_argument("--no-pure", dest="pure", action="store_false",
                   help="Force full context even for short prompts")

    # tui (explicit; bare `j5` also lands here)
    sub.add_parser("tui", parents=[json_sub], help="Open the interactive terminal UI")

    # capabilities (read-only; inspectable even in readonly mode)
    sub.add_parser("capabilities", parents=[json_sub], help="Show the per-command mutation boundary map")

    # Drift guard: every subcommand must have a capability entry, or the
    # readonly gate cannot reason about it. Fails at parser construction
    # (loudly, everywhere) instead of failing open at runtime.
    unmapped = sorted(set(sub.choices) - set(COMMAND_CAPABILITIES))
    if unmapped:
        raise ValueError(f"subcommands missing from COMMAND_CAPABILITIES: {unmapped}")

    return parser


def cmd_tui(args: argparse.Namespace) -> int:
    """Launch the interactive terminal UI (Textual, curses, or ANSI fallback)."""
    try:
        from j5_tui.app import run_tui
    except Exception as exc:  # noqa: BLE001 - never break the CLI on TUI import failure
        print(f"Could not start the interactive UI: {type(exc).__name__}: {exc}", file=sys.stderr)
        print("Subcommands still work, e.g. `j5 status`, `j5 run --prompt ...`.", file=sys.stderr)
        return 1
    try:
        run_tui()
    except KeyboardInterrupt:
        print("\nBye.")
    return 0


def cmd_capabilities(args: argparse.Namespace) -> int:
    """Print the per-command mutation boundary map."""
    if args.json:
        print(json.dumps(COMMAND_CAPABILITIES, indent=2))
        return 0
    print(f"{'command':<12} {'worker':<7} {'project':<8} state")
    print("-" * 40)
    for cmd in sorted(COMMAND_CAPABILITIES):
        caps = COMMAND_CAPABILITIES[cmd]
        cell = lambda v: "yes" if v else "no"  # noqa: E731 - tiny local formatter
        print(f"{cmd:<12} {cell(caps['spawns_worker']):<7} "
              f"{cell(caps['mutates_project']):<8} {cell(caps['mutates_harness_state'])}")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = bool(getattr(args, "global_json", False) or getattr(args, "sub_json", False))

    commands = {
        "route": cmd_route,
        "status": cmd_status,
        "projects": cmd_projects,
        "domains": cmd_domains,
        "skills": cmd_skills,
        "probe": cmd_probe,
        "watch": cmd_watch,
        "config": cmd_config,
        "benchmark": cmd_benchmark,
        "sessions": cmd_sessions,
        "doctor": cmd_doctor,
        "run": cmd_run,
        "tui": cmd_tui,
        "capabilities": cmd_capabilities,
    }

    # Bare `j5` opens the interactive UI, like bare `opencode` / `hermes`.
    effective = args.command or "tui"

    # Readonly gate: refuse anything that spawns or writes, before it runs.
    # Fail closed: a command missing from the map is refused, never allowed.
    source = readonly_source(args)
    if source:
        caps = COMMAND_CAPABILITIES.get(effective)
        if caps is None:
            print(fail_line(f"Error: '{effective}' has no capability entry; "
                            f"refusing in readonly mode ({source})",
                            enabled=supports_color(sys.stderr)), file=sys.stderr)
            return READONLY_EXIT_CODE
        triggered = sorted(k for k, v in caps.items() if v)
        if triggered:
            reasons = ", ".join(_CAPABILITY_REASONS[k] for k in triggered)
            err = supports_color(sys.stderr)
            print(fail_line(f"Error: '{effective}' is blocked in readonly mode ({source})",
                            enabled=err), file=sys.stderr)
            print(f"  It would {reasons}.", file=sys.stderr)
            print(hint("Re-run without --readonly (or unset J5_READONLY) to allow mutation."),
                  file=sys.stderr)
            return READONLY_EXIT_CODE

    if effective not in commands:
        parser.print_help()
        return 1

    return commands[effective](args)


if __name__ == "__main__":
    sys.exit(main())