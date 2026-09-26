#!/usr/bin/env python3
"""
J5 Harness TUI — Terminal User Interface for the J5 Harness.

Features:
- Dashboard with real-time status
- Project/domain navigation
- Routing decisions visualization
- Kilo probe management
- Live logs
- Configuration viewer
- Benchmark runner
- Skills explorer
"""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap
import threading
from pathlib import Path
from typing import Any, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

# Ensure UTF-8 output on Windows consoles for Unicode marks and borders
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

try:
    from textual.app import App, ComposeResult
    from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
    from textual.widgets import (
        Header, Footer, Static, Button, DataTable, Tree,
        Input, Log, RichLog, TabbedContent, TabPane, Label, Select
    )
    from textual.reactive import reactive
    from textual.binding import Binding
    from textual.screen import Screen
    from textual.message import Message
    TEXTUAL_AVAILABLE = True
except ImportError:
    TEXTUAL_AVAILABLE = False

try:
    import curses
    from curses import wrapper
    CURSES_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    CURSES_AVAILABLE = False
    curses = None
    wrapper = None

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
    SHARED,
)
from tools.harness.watch_kilo import process_once as watch_once
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
    PALETTE,
    textual_css,
    init_curses_pairs,
    ANSI,
    color,
    title,
    separator,
)


class J5HarnessData:
    """Data provider for the TUI."""
    
    def __init__(self) -> None:
        self.config: Optional[dict[str, Any]] = None
        self.domain_registry: Optional[DomainRegistry] = None
        self.project_registry: Optional[ProjectRegistry] = None
        self.multi_router: Optional[MultiProjectRouter] = None
        self._load_data()
    
    def _load_data(self) -> None:
        try:
            self.config = load_config()
            self.domain_registry = DomainRegistry()
            self.project_registry = ProjectRegistry()
            self.multi_router = MultiProjectRouter()
            if self.project_registry:
                for p in self.project_registry.list_projects():
                    try:
                        self.multi_router.get_router(p)
                    except Exception:
                        pass
        except Exception as e:
            print(f"Error loading data: {e}", file=sys.stderr)
    
    def get_projects(self) -> list[str]:
        if self.project_registry:
            return self.project_registry.list_projects()
        return []
    
    def get_domains(self) -> list[str]:
        if self.domain_registry:
            return self.domain_registry.list_domains()
        return []
    
    def get_project_status(self, project: str) -> dict[str, Any]:
        if not self.multi_router or not project:
            return {}
        try:
            router = self.multi_router.get_router(project)
            return router.status()
        except Exception:
            return {}
    
    def get_global_status(self) -> dict[str, Any]:
        if self.multi_router:
            return self.multi_router.global_status()
        return {}
    
    def get_routing_decision(self, project: str, task_type: str):
        if self.multi_router and project and task_type:
            try:
                return self.multi_router.pick(project, task_type)
            except Exception:
                return None
        return None
    
    def run_probe(self, project: str, probe_id: str, prompt: str) -> dict[str, Any]:
        if not project:
            return {"error": "no project specified"}
        try:
            config = load_config()
            kilo_cfg = config.get("kilo", {})
            if not kilo_cfg:
                return {"error": "kilo config not found"}
            contexts = build_project_contexts(config, "coder")
            ctx = next((c for c in contexts if c.name == project), contexts[0] if contexts else None)
            if ctx is None:
                return {"error": f"no project context found for {project}"}
            return run_probe_roundtrip(ctx, probe_id, prompt, kilo_cfg)
        except Exception as e:
            return {"error": str(e)}
    
    def get_skills(self, project: str):
        if not project:
            return []
        try:
            proj = load_project_config(project)
            hub = SkillHub(roots=[Path(r) for r in proj.get_all_skills()])
            skills = hub.list_skills()
            if skills:
                return skills
            return proj.get_all_skills()
        except Exception:
            return []


# Global data instance
DATA = J5HarnessData()


if TEXTUAL_AVAILABLE:
    class DashboardScreen(Screen):
        """Main dashboard screen."""
        
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("p", "projects", "Projects"),
            Binding("d", "domains", "Domains"),
            Binding("r", "routing", "Routing"),
            Binding("k", "kilo", "Kilo"),
            Binding("s", "skills", "Skills"),
            Binding("b", "benchmark", "Benchmark"),
            Binding("l", "logs", "Logs"),
            Binding("c", "config", "Config"),
        ]
        
        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Footer()
            with Container(id="main"):
                with Horizontal():
                    with Vertical(id="sidebar"):
                        yield Static("J5 HARNESS", id="title")
                        yield Button("Projects", id="btn-projects", variant="primary")
                        yield Button("Domains", id="btn-domains")
                        yield Button("Routing", id="btn-routing")
                        yield Button("Kilo", id="btn-kilo")
                        yield Button("Skills", id="btn-skills")
                        yield Button("Benchmark", id="btn-benchmark")
                        yield Button("Logs", id="btn-logs")
                        yield Button("Config", id="btn-config")
                    with Vertical(id="content"):
                        yield Static(id="content-area")
        
        def on_button_pressed(self, event: Button.Pressed) -> None:
            button_id = event.button.id
            if button_id == "btn-projects":
                self.action_projects()
            elif button_id == "btn-domains":
                self.action_domains()
            elif button_id == "btn-routing":
                self.action_routing()
            elif button_id == "btn-kilo":
                self.action_kilo()
            elif button_id == "btn-skills":
                self.action_skills()
            elif button_id == "btn-benchmark":
                self.action_benchmark()
            elif button_id == "btn-logs":
                self.action_logs()
            elif button_id == "btn-config":
                self.action_config()
        
        def action_quit(self) -> None:
            self.app.exit()
        
        def action_projects(self) -> None:
            self.app.push_screen(ProjectsScreen())
        
        def action_domains(self) -> None:
            self.app.push_screen(DomainsScreen())
        
        def action_routing(self) -> None:
            self.app.push_screen(RoutingScreen())
        
        def action_kilo(self) -> None:
            self.app.push_screen(KiloScreen())
        
        def action_skills(self) -> None:
            self.app.push_screen(SkillsScreen())
        
        def action_benchmark(self) -> None:
            self.app.push_screen(BenchmarkScreen())
        
        def action_logs(self) -> None:
            self.app.push_screen(LogsScreen())
        
        def action_config(self) -> None:
            self.app.push_screen(ConfigScreen())
        
        def on_mount(self) -> None:
            self.update_dashboard()
            self.set_interval(5, self.update_dashboard)
        
        def update_dashboard(self) -> None:
            content = self.query_one("#content-area", Static)
            status = DATA.get_global_status()
            
            lines = ["J5 HARNESS DASHBOARD", "=" * 50, ""]
            projects_dict = status.get('projects', {})
            lines.append(f"Projects: {len(projects_dict)}")
            lines.append(f"Models tracked: {len(status.get('shared_health', {}))}")
            lines.append(f"Models scored: {len(status.get('shared_scores', {}))}")
            lines.append("")
            
            for name, proj_status in projects_dict.items():
                domain = proj_status.get('domain', 'unknown')
                in_flight = proj_status.get('in_flight', 0)
                max_flight = proj_status.get('max_in_flight', 1)
                quarantined = proj_status.get('quarantined', [])
                q_text = ", ".join(quarantined) if quarantined else "none"
                lines.append(f"  {name} ({domain}):")
                lines.append(f"    In-flight:   {in_flight}/{max_flight}")
                lines.append(f"    Quarantined: {q_text}")
            
            content.update("\n".join(lines))
    
    class ProjectsScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            yield DataTable(id="projects-table")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.add_columns("Project", "Domain", "Status", "Directory")
            for p in DATA.get_projects():
                proj = DATA.project_registry.get_project(p) if DATA.project_registry else None
                if proj:
                    table.add_row(p, proj.domain, "enabled" if proj.enabled else "disabled", proj.project_dir)
                else:
                    table.add_row(p, "unknown", "unknown", "")
    
    class DomainsScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            yield DataTable(id="domains-table")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.add_columns("Domain", "Description", "Models", "Skills", "Tools")
            for d in DATA.get_domains():
                dom = DATA.domain_registry.get_domain(d) if DATA.domain_registry else None
                if dom:
                    table.add_row(
                        d, dom.description[:40],
                        f"{len(dom.models.primary)}+{len(dom.models.fallback)}",
                        str(len(dom.skills)),
                        str(len(dom.tools))
                    )
    
    class RoutingScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            with Vertical():
                with Horizontal():
                    yield Select(
                        [(p, p) for p in DATA.get_projects()],
                        prompt="Project",
                        id="project-select"
                    )
                    yield Select(
                        [("coding", "coding"), ("research", "research"), 
                         ("analysis", "analysis"), ("conversation", "conversation")],
                        prompt="Task Type",
                        id="task-select"
                    )
                yield Button("Get Decision", id="btn-decide", variant="primary")
                yield Static(id="routing-result")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-decide":
                project = self.query_one("#project-select", Select).value
                task_type = self.query_one("#task-select", Select).value
                result = self.query_one("#routing-result", Static)
                if not project or project is Select.BLANK or not task_type or task_type is Select.BLANK:
                    result.update("Please select both a Project and a Task Type.")
                    return
                decision = DATA.get_routing_decision(str(project), str(task_type))
                if decision:
                    result.update(f"""Routing Decision:
  Project:  {decision.project}
  Domain:   {decision.domain}
  Task:     {decision.task_type}
  Model:    {decision.model}
  Endpoint: {decision.endpoint}
  Latency:  {decision.expected_latency_ms:.1f}ms
  Reason:   {decision.reason}
  Chain:    {' -> '.join(decision.chain)}""")
                else:
                    result.update("Error: Could not get routing decision")
    
    class KiloScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            with Vertical():
                with Horizontal():
                    yield Select(
                        [(p, p) for p in DATA.get_projects()],
                        prompt="Project",
                        id="kilo-project"
                    )
                    yield Input(placeholder="Probe ID", id="probe-id")
                    yield Input(placeholder="Prompt", id="probe-prompt")
                yield Button("Run Probe", id="btn-probe", variant="primary")
                yield Button("Run Watcher Once", id="btn-watch", variant="default")
                yield Static(id="kilo-result")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_button_pressed(self, event: Button.Pressed) -> None:
            result_widget = self.query_one("#kilo-result", Static)
            if event.button.id == "btn-probe":
                project = self.query_one("#kilo-project", Select).value
                if not project or project is Select.BLANK:
                    result_widget.update("Error: Please select a project.")
                    return
                probe_id = self.query_one("#probe-id", Input).value or "probe-001"
                prompt = self.query_one("#probe-prompt", Input).value or "Test probe"
                result = DATA.run_probe(str(project), probe_id, prompt)
                result_widget.update(json.dumps(result, indent=2))
            elif event.button.id == "btn-watch":
                try:
                    watch_once()
                    result_widget.update("Watcher cycle completed")
                except Exception as e:
                    result_widget.update(f"Watcher error: {e}")
    
    class SkillsScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            with Vertical():
                yield Select(
                    [(p, p) for p in DATA.get_projects()],
                    prompt="Project",
                    id="skills-project"
                )
                yield DataTable(id="skills-table")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_mount(self) -> None:
            table = self.query_one(DataTable)
            table.add_columns("Identity", "Version", "Source", "Capabilities")
            projects = DATA.get_projects()
            if projects:
                self.query_one("#skills-project", Select).value = projects[0]
            self.update_skills()
        
        def on_select_changed(self, event: Select.Changed) -> None:
            self.update_skills()
        
        def update_skills(self) -> None:
            project = self.query_one("#skills-project", Select).value
            table = self.query_one(DataTable)
            table.clear()
            if project and project is not Select.BLANK:
                skills = DATA.get_skills(str(project))
                for s in skills:
                    if hasattr(s, "identity"):
                        table.add_row(
                            s.identity,
                            str(getattr(s, "version", "")),
                            getattr(s, "source", ""),
                            ", ".join(getattr(s, "capabilities", [])[:3])
                        )
                    elif isinstance(s, str):
                        table.add_row(s, "-", "domain", "-")
    
    class BenchmarkScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            with Vertical():
                yield Button("Run All Benchmarks", id="btn-bench", variant="primary")
                yield Static(id="bench-results")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "btn-bench":
                result_widget = self.query_one("#bench-results", Static)
                result_widget.update("Running benchmarks...")
                
                try:
                    def dummy_task(x):
                        import time
                        time.sleep(0.001)
                        return x * 2
                    
                    bench = run_benchmark(
                        lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
                        BenchmarkConfig(iterations=10, warmup=2),
                        "parallel_executor_100_tasks"
                    )
                    
                    cache = MultiTierCache(CacheConfig(l1_max_entries=10000, enable_l2=False))
                    for i in range(1000):
                        cache.set(f"key{i}", f"value{i}")
                    
                    bench2 = run_benchmark(
                        lambda: [cache.get(f"key{i}") for i in range(100)],
                        BenchmarkConfig(iterations=50, warmup=5),
                        "cache_get_100_keys"
                    )
                    
                    long_text = "This is a test prompt. " * 500
                    bench3 = run_benchmark(
                        lambda: compress_context(long_text, CompressionConfig(target_tokens=1000)),
                        BenchmarkConfig(iterations=20, warmup=3),
                        "context_compression"
                    )
                    
                    result_widget.update(f"""Parallel Executor (100 tasks):
  p50: {bench.latency_ms['p50']:.2f}ms | p95: {bench.latency_ms['p95']:.2f}ms | p99: {bench.latency_ms['p99']:.2f}ms
  Throughput: {bench.throughput_per_s:.1f}/s | Errors: {bench.error_rate:.2%}

Cache (100 keys):
  p50: {bench2.latency_ms['p50']:.2f}ms | p95: {bench2.latency_ms['p95']:.2f}ms | p99: {bench2.latency_ms['p99']:.2f}ms
  Throughput: {bench2.throughput_per_s:.1f}/s | Errors: {bench2.error_rate:.2%}

Compression:
  p50: {bench3.latency_ms['p50']:.2f}ms | p95: {bench3.latency_ms['p95']:.2f}ms | p99: {bench3.latency_ms['p99']:.2f}ms
  Throughput: {bench3.throughput_per_s:.1f}/s | Errors: {bench3.error_rate:.2%}""")
                except Exception as e:
                    result_widget.update(f"Benchmark error: {e}")
    
    class LogsScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            yield Log(id="log-view", highlight=True)
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_mount(self) -> None:
            log = self.query_one(Log)
            log.write_line(f"[bold {PALETTE['accent_blue']}]J5 Harness Logs[/]")
            log.write_line(f"[dim {PALETTE['border']}]{'=' * 50}[/]")
            sample_logs = [
                (PALETTE["success"], "INFO", "System event: heartbeat"),
                (PALETTE["success"], "INFO", "Router initialized for enabled projects"),
                (PALETTE["warning"], "WARN", "System event: slow heartbeat on nemotron"),
                (PALETTE["error"], "ERROR", "Probe failed on endpoint backup: connection timeout"),
                (PALETTE["success"], "INFO", "Kilo inbox watcher completed scan (0 pending)"),
                (PALETTE["success"], "INFO", "Latency cache warmup completed (1000 keys)"),
                (PALETTE["warning"], "WARN", "Rate limit headroom low on shared Zen IP bucket"),
                (PALETTE["success"], "INFO", "Delegation ledger verified integrity"),
            ]
            for color_code, level, msg in sample_logs:
                log.write_line(f"[{color_code}][{level}][/] {msg}")
    
    class ConfigScreen(Screen):
        BINDINGS = [Binding("escape", "pop_screen", "Back")]
        
        def compose(self) -> ComposeResult:
            yield Header()
            yield Footer()
            with ScrollableContainer(id="config-container"):
                yield Static(id="config-view")
        
        def action_pop_screen(self) -> None:
            self.app.pop_screen()
        
        def on_mount(self) -> None:
            try:
                config = load_config()
                view = self.query_one("#config-view", Static)
                view.update(json.dumps(config, indent=2))
            except Exception as e:
                self.query_one("#config-view", Static).update(f"Error loading config: {e}")
    
    class ChatScreen(Screen):
        """Prompt-first harness console: ask, stream, verify, continue.

        Every turn runs the full harness path (domain route -> fallback
        chain -> worker -> ledger + health), with the worker's answer
        streaming live into the transcript and the worker session carried
        across turns — the opencode / Claude Code / Codex interaction
        model, backed by J5 routing and verification instead of a single
        model. Esc shows the dashboard; the run keeps going and lands in
        the ledger either way.
        """

        BINDINGS = [
            Binding("escape", "show_board", "Board"),
            Binding("up", "hist_prev", "History back"),
            Binding("down", "hist_next", "History forward"),
            Binding("f1", "show_help", "Help"),
        ]
        WRAP_WIDTH = 100
        HISTORY_MAX = 500

        def __init__(self) -> None:
            super().__init__()
            self.busy = False
            self.session_id: str | None = None
            self.turn = 0
            self._buf = ""
            self._answer_label = None
            self.history: list[str] = []
            self._hist_idx = 0

        def compose(self) -> ComposeResult:
            yield Header()
            projects = DATA.get_projects() or ["wsb-alpha"]
            with ScrollableContainer(id="chat-scroll"):
                yield Label("Ask J5 anything. Routing, fallback, verification, and ledger happen automatically. "
                            "'a' focuses here from anywhere; Esc shows the dashboard.")
            yield Label("Ready. Type a task, Enter sends — F1 for keys.", id="chat-status")
            with Horizontal(id="chat-bar"):
                yield Select([(p, p) for p in projects], value=projects[0], id="chat-project")
                yield Select([("coding", "coding"), ("research", "research"),
                              ("analysis", "analysis"), ("conversation", "conversation")],
                             value="coding", id="chat-task")
                yield Input(placeholder="Type a task and hit Enter…", id="chat-input")
                yield Button("Send", id="chat-send", variant="primary")
                yield Button("Stop", id="chat-stop")
                yield Button("New chat", id="chat-new")
            yield Footer()

        def on_mount(self) -> None:
            self._load_history()
            try:
                self.query_one("#chat-input", Input).focus()
            except Exception:
                pass

        def action_show_board(self) -> None:
            self.app.push_screen(DashboardScreen())

        def on_button_pressed(self, event: Button.Pressed) -> None:
            pressed = event.button.id
            if pressed == "chat-send":
                self._submit()
            elif pressed == "chat-stop":
                self._stop()
            elif pressed == "chat-new":
                self._new_chat()

        def on_input_submitted(self, event: Input.Submitted) -> None:
            if event.input.id == "chat-input":
                self._submit()

        # -- UI-thread helpers (never call widgets from the worker) -----
        def _scroll(self) -> None:
            try:
                self.query_one("#chat-scroll", ScrollableContainer).scroll_end(animate=False)
            except Exception:
                pass

        def _add(self, text: str) -> None:
            try:
                wrapped = "\n".join(textwrap.wrap(text, self.WRAP_WIDTH) or [""])
                self.query_one("#chat-scroll", ScrollableContainer).mount(Label(wrapped))
                self._scroll()
            except Exception:
                pass

        def _submit(self) -> None:
            if self.busy:
                self._add("…a turn is already running — Stop cancels it, "
                          "finished turns land in the ledger either way.")
                return
            try:
                prompt = self.query_one("#chat-input", Input).value.strip()
                project = str(self.query_one("#chat-project", Select).value or "wsb-alpha")
                task_type = str(self.query_one("#chat-task", Select).value or "coding")
            except Exception:
                return
            if not prompt:
                return
            self.query_one("#chat-input", Input).value = ""
            if not self.history or self.history[-1] != prompt:
                self.history.append(prompt)
                self._save_history()
            self._hist_idx = len(self.history)
            self.busy = True
            self.turn += 1
            self._buf = ""
            self._add(f"── you → {project} [{task_type}] · turn {self.turn} ──")
            self._add(prompt)
            self._answer_label = Label("▸ routing…")
            try:
                self.query_one("#chat-scroll", ScrollableContainer).mount(self._answer_label)
            except Exception:
                self._answer_label = None
            threading.Thread(target=self._run_turn,
                             args=(project, task_type, prompt, self.turn),
                             daemon=True).start()

        def _on_chunk(self, chunk: str) -> None:
            self.app.call_from_thread(self._append_chunk, chunk)

        def _append_chunk(self, chunk: str) -> None:
            if self._answer_label is None:
                return
            try:
                self._buf += chunk
                wrapped = "\n".join(textwrap.wrap(self._buf, self.WRAP_WIDTH) or [""])
                self._answer_label.update(wrapped)
                self._scroll()
            except Exception:
                pass

        def _stop(self) -> None:
            try:
                from tools.harness.integration import SHARED
                adapter = getattr(SHARED, "adapter", None)
                if hasattr(adapter, "terminate_current"):
                    adapter.terminate_current()
                    self._add("■ stop requested — worker terminating; partial output (if any) is kept.")
                else:
                    self._add("■ stop unavailable on this gateway.")
            except Exception as exc:  # noqa: BLE001 - show, never crash
                self._add(f"stop failed: {exc}")

        def _new_chat(self) -> None:
            self.session_id = None
            self.turn = 0
            try:
                scroll = self.query_one("#chat-scroll", ScrollableContainer)
                scroll.remove_children()
                scroll.mount(Label("New chat. Worker session reset; ledger history is kept per project."))
            except Exception:
                pass

        def _history_path(self):  # Path import kept local: stdlib only
            from pathlib import Path
            return Path.home() / ".j5" / "chat_history.jsonl"

        def _load_history(self) -> None:
            try:
                lines = self._history_path().read_text(encoding="utf-8").splitlines()
                self.history = [json.loads(l) for l in lines if l.strip()][-self.HISTORY_MAX:]
            except Exception:
                self.history = []
            self._hist_idx = len(self.history)

        def _save_history(self) -> None:
            try:
                p = self._history_path()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("\n".join(json.dumps(h) for h in self.history[-self.HISTORY_MAX:]),
                             encoding="utf-8")
            except Exception:
                pass  # history is a convenience; never break a turn over it

        def _focused_input(self) -> bool:
            try:
                w = self.focused
                return isinstance(w, Input) and w.id == "chat-input"
            except Exception:
                return False

        def action_hist_prev(self) -> None:
            if not self._focused_input() or not self.history:
                return
            self._hist_idx = max(0, self._hist_idx - 1)
            self.query_one("#chat-input", Input).value = self.history[self._hist_idx]

        def action_hist_next(self) -> None:
            if not self._focused_input() or not self.history:
                return
            if self._hist_idx >= len(self.history) - 1:
                self._hist_idx = len(self.history)
                self.query_one("#chat-input", Input).value = ""
            else:
                self._hist_idx += 1
                self.query_one("#chat-input", Input).value = self.history[self._hist_idx]

        def action_show_help(self) -> None:
            self.app.push_screen(ChatHelpScreen())

        # -- worker thread (never touch widgets here) --------------------
        def _run_turn(self, project: str, task_type: str, prompt: str, turn: int) -> None:
            emit = self.app.call_from_thread
            try:
                from tools.delegation.ledger import DelegationLedger
                from tools.delegation.orchestrator import Orchestrator
                from tools.harness.integration import (
                    SHARED, build_project_contexts, load_config, make_router_fn,
                )
                config = load_config()
                contexts = {c.name: c for c in build_project_contexts(config, "coder")}
                if project not in contexts:
                    raise ValueError(f"unknown project {project!r}")
                ctx = contexts[project]
                task_id = f"chat-{turn:03d}"
                ledger = DelegationLedger(ctx.ledger_path)
                router_fn = make_router_fn(ctx, SHARED, config)
                orch = Orchestrator(ledger=ledger, router_fn=router_fn)
                dag = orch.decompose(prompt, [{"task_id": task_id, "prompt": prompt}])
                emit(self._set_status, f"▸ dispatched {task_id} · streaming…")
                dag = orch.run(dag, task_type=task_type,
                               on_text=self._on_chunk, session_id=self.session_id)
                node = dag.nodes[task_id]
                if getattr(node, "session_id", None):
                    self.session_id = node.session_id
                emit(self._finish, node.state.name, node.model_id or "?",
                     float(node.confidence or 0.0), str(ctx.ledger_path),
                     getattr(node, "usage", None) or {})
            except Exception as exc:  # noqa: BLE001 - show, never crash the TUI
                emit(self._add, f"✖ turn failed: {type(exc).__name__}: {str(exc)[:300]}")
            finally:
                emit(self._set_busy, False)

        def _set_status(self, text: str) -> None:
            if self._answer_label is not None:
                try:
                    self._answer_label.update(text)
                except Exception:
                    pass

        def _set_busy(self, value: bool) -> None:
            self.busy = value

        def _finish(self, state: str, model: str, conf: float, ledger: str,
                    usage: dict | None = None) -> None:
            if not self._buf:
                self._append_chunk("(empty response)")
            continued = f" · session kept ({self.session_id})" if self.session_id else ""
            self._add(f"── {state} via {model} · conf {conf:.2f}{continued} ──")
            try:
                toks = (usage or {}).get("tokens_total", "-")
                self.query_one("#chat-status", Label).update(
                    f"{model} · conf {conf:.2f} · tokens {toks} · turn {self.turn}")
            except Exception:
                pass


    class ChatHelpScreen(Screen):
        """Key map for the chat console. Esc closes."""

        BINDINGS = [Binding("escape", "pop_screen", "Close")]

        def action_pop_screen(self) -> None:
            self.app.pop_screen()

        def compose(self) -> ComposeResult:
            yield Header()
            yield Label("Chat keys", id="help-title")
            yield Label(
                "Enter       send prompt\n"
                "Up / Down   command history (while typing)\n"
                "F1          this help\n"
                "Esc         dashboard — the run keeps going\n"
                "a           focus chat from anywhere\n"
                "q / Ctrl+C  quit the TUI",
                id="help-body",
            )
            yield Footer()


    class J5TUIApp(App):
        """Main J5 Harness TUI Application."""
        
        TITLE = "J5 Harness"
        SUB_TITLE = "Multi-domain coding harness"
        
        # Black theme (spec-ui-black-theme.md section 5): textual CSS tokens
        # for Screen, Header, Footer, Sidebar, Buttons, DataTables, Selects,
        # Inputs, Logs, and Containers.
        CSS = textual_css() + f"""
        Screen {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
        }}
        Header {{
            background: {PALETTE["bg_panel"]};
            color: {PALETTE["text"]};
        }}
        Footer {{
            background: {PALETTE["bg_panel"]};
            color: {PALETTE["text_muted"]};
        }}
        Footer > .footer--key {{
            color: {PALETTE["accent_blue"]};
            background: {PALETTE["bg_elevated"]};
        }}
        Footer > .footer--highlight {{
            background: {PALETTE["bg_hover"]};
        }}
        #sidebar {{
            width: 24;
            background: {PALETTE["bg_panel"]};
            border-right: tall {PALETTE["border"]};
            padding: 0 1;
        }}
        #sidebar Button {{
            width: 100%;
            margin-bottom: 1;
        }}
        #title {{
            color: {PALETTE["accent_blue"]};
            text-style: bold;
            text-align: center;
            padding: 1 0;
            background: {PALETTE["bg_panel"]};
        }}
        #content {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
            padding: 1 2;
        }}
        #content-area {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
        }}
        Button {{
            background: {PALETTE["bg_elevated"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border"]};
        }}
        Button:hover {{
            background: {PALETTE["bg_hover"]};
            border: tall {PALETTE["border_focus"]};
        }}
        Button:focus {{
            border: tall {PALETTE["border_focus"]};
        }}
        Button.-primary, Button.primary {{
            background: {PALETTE["accent_blue"]};
            color: {PALETTE["bg_base"]};
            border: tall {PALETTE["accent_blue"]};
            text-style: bold;
        }}
        Button.-primary:hover, Button.primary:hover {{
            background: {PALETTE["text"]};
            color: {PALETTE["bg_base"]};
        }}
        DataTable {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border_subtle"]};
        }}
        DataTable > .datatable--header {{
            background: {PALETTE["bg_elevated"]};
            color: {PALETTE["text_muted"]};
            text-style: bold;
        }}
        DataTable > .datatable--cursor {{
            background: {PALETTE["bg_selected"]};
            color: {PALETTE["text"]};
        }}
        DataTable > .datatable--hover {{
            background: {PALETTE["bg_hover"]};
        }}
        Select {{
            background: {PALETTE["bg_base"]};
            border: tall {PALETTE["border"]};
            color: {PALETTE["text"]};
        }}
        Select:focus {{
            border: tall {PALETTE["border_focus"]};
        }}
        SelectCurrent {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border"]};
        }}
        SelectOverlay {{
            background: {PALETTE["bg_panel"]};
            border: tall {PALETTE["border"]};
            color: {PALETTE["text"]};
        }}
        SelectOverlay > OptionList {{
            background: {PALETTE["bg_panel"]};
            color: {PALETTE["text"]};
        }}
        OptionList > .option-list--option.-highlighted {{
            background: {PALETTE["bg_selected"]};
            color: {PALETTE["text"]};
        }}
        Input {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border"]};
        }}
        Input:focus {{
            border: tall {PALETTE["border_focus"]};
        }}
        Log {{
            background: {PALETTE["bg_base"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border_subtle"]};
        }}
        #routing-result, #kilo-result, #bench-results, #config-view {{
            background: {PALETTE["bg_panel"]};
            color: {PALETTE["text"]};
            border: tall {PALETTE["border_subtle"]};
            padding: 1;
            margin-top: 1;
        }}
        #config-container {{
            background: {PALETTE["bg_base"]};
        }}
        ScrollableContainer {{
            background: {PALETTE["bg_base"]};
            scrollbar-color: {PALETTE["bg_elevated"]};
            scrollbar-color-hover: {PALETTE["bg_hover"]};
            scrollbar-color-active: {PALETTE["border_focus"]};
            scrollbar-background: {PALETTE["bg_base"]};
        }}
        #chat-scroll {{
            height: 1fr;
            border: tall {PALETTE["border_subtle"]};
            background: {PALETTE["bg_base"]};
            padding: 0 1;
        }}
        #chat-bar {{
            height: auto;
            margin-top: 1;
        }}
        #chat-status {{
            color: {PALETTE["text_muted"]};
            padding: 0 1;
        }}
        #help-body {{
            padding: 1 2;
        }}
        #chat-bar Input {{
            width: 1fr;
        }}
        #chat-bar Select {{
            width: 26;
        }}
        """
        
        BINDINGS = [
            Binding("q", "quit", "Quit"),
            Binding("ctrl+c", "quit", "Quit"),
            Binding("a", "chat", "Ask"),
        ]

        def action_chat(self) -> None:
            if type(self.screen).__name__ == "ChatScreen":
                try:
                    self.screen.query_one("#chat-input", Input).focus()
                except Exception:
                    pass
            else:
                self.push_screen(ChatScreen())

        def on_mount(self) -> None:
            # Prompt-first: land on the chat console like opencode/claude/codex.
            self.push_screen(ChatScreen())


# ---------------------------------------------------------------------------
# Curses fallback TUI (POSIX and Windows with windows-curses)
# ---------------------------------------------------------------------------

def run_curses_tui(stdscr: Any) -> None:
    """Curses-based fallback TUI."""
    curses.curs_set(0)
    stdscr.clear()
    
    # Color pairs from the shared black theme (spec-ui-black-theme.md
    # section 5): text, selection, accent, warn, error, success.
    curses.start_color()
    pairs = init_curses_pairs(stdscr)
    
    height, width = stdscr.getmaxyx()
    
    menu_items = [
        "1. Dashboard",
        "2. Projects",
        "3. Domains",
        "4. Routing",
        "5. Kilo Probe",
        "6. Skills",
        "7. Benchmark",
        "8. Logs",
        "9. Config",
        "q. Quit",
    ]
    
    current_selection = 0
    
    def draw_menu():
        stdscr.clear()
        stdscr.addstr(0, 0, "J5 HARNESS TUI", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        
        for i, item in enumerate(menu_items):
            y = 3 + i
            if y >= height - 3:
                break
            if i == current_selection:
                stdscr.addstr(y, 2, f"> {item}", curses.color_pair(pairs["selection"]) | curses.A_BOLD)
            else:
                stdscr.addstr(y, 2, f"  {item}", curses.color_pair(pairs["text"]))
        
        footer_y = max(0, height - 2)
        stdscr.addstr(footer_y, 0, "Use UP/DOWN to navigate, ENTER to select, q to quit"[:width - 1], curses.color_pair(pairs["accent"]))
        stdscr.refresh()
    
    while True:
        draw_menu()
        key = stdscr.getch()
        
        if key == curses.KEY_UP and current_selection > 0:
            current_selection -= 1
        elif key == curses.KEY_DOWN and current_selection < len(menu_items) - 1:
            current_selection += 1
        elif key in (ord('\n'), curses.KEY_ENTER):
            if current_selection == len(menu_items) - 1:  # Quit
                break
            handle_selection(current_selection, stdscr, pairs)
        elif key in (ord('q'), ord('Q')):
            break


def handle_selection(selection: int, stdscr: Any, pairs: dict[str, int]) -> None:
    """Handle menu selection in curses mode."""
    height, width = stdscr.getmaxyx()
    stdscr.clear()
    
    if selection == 0:  # Dashboard
        status = DATA.get_global_status()
        stdscr.addstr(0, 0, "DASHBOARD", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        projects_dict = status.get('projects', {})
        stdscr.addstr(3, 0, f"Projects:       {len(projects_dict)}", curses.color_pair(pairs["text"]))
        stdscr.addstr(4, 0, f"Models tracked: {len(status.get('shared_health', {}))}", curses.color_pair(pairs["text"]))
        stdscr.addstr(5, 0, f"Models scored:  {len(status.get('shared_scores', {}))}", curses.color_pair(pairs["text"]))
        
        row = 7
        for name, proj_status in projects_dict.items():
            if row >= height - 3:
                break
            domain = proj_status.get('domain', 'unknown')
            in_flight = proj_status.get('in_flight', 0)
            max_flight = proj_status.get('max_in_flight', 1)
            quarantined = proj_status.get('quarantined', [])
            stdscr.addstr(row, 0, f"  {name} ({domain}):", curses.color_pair(pairs["accent"]))
            q_color = pairs["warn"] if quarantined else pairs["text"]
            q_str = ", ".join(quarantined) if quarantined else "none"
            stdscr.addstr(row + 1, 0, f"    In-flight: {in_flight}/{max_flight} | Quarantined: {q_str}", curses.color_pair(q_color))
            row += 3

    elif selection == 1:  # Projects
        stdscr.addstr(0, 0, "PROJECTS", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        projects = DATA.get_projects()
        for i, p in enumerate(projects):
            if 3 + i >= height - 3:
                break
            proj = DATA.project_registry.get_project(p) if DATA.project_registry else None
            status_str = "enabled" if (proj and proj.enabled) else "disabled"
            status_pair = pairs["success"] if (proj and proj.enabled) else pairs["warn"]
            domain_str = proj.domain if proj else "unknown"
            dir_str = proj.project_dir if proj else ""
            stdscr.addstr(3 + i, 0, f"  {p:<16} [{domain_str}] ", curses.color_pair(pairs["accent"]))
            stdscr.addstr(status_str, curses.color_pair(status_pair))
            stdscr.addstr(f"  {dir_str}", curses.color_pair(pairs["text"]))

    elif selection == 2:  # Domains
        stdscr.addstr(0, 0, "DOMAINS", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        domains = DATA.get_domains()
        for i, d in enumerate(domains):
            if 3 + i >= height - 3:
                break
            dom = DATA.domain_registry.get_domain(d) if DATA.domain_registry else None
            desc = dom.description[:45] if dom else ""
            stdscr.addstr(3 + i, 0, f"  {d:<12}: {desc}", curses.color_pair(pairs["text"]))

    elif selection == 3:  # Routing
        stdscr.addstr(0, 0, "ROUTING DECISION", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        projects = DATA.get_projects()
        proj_name = projects[0] if projects else "wsb-alpha"
        decision = DATA.get_routing_decision(proj_name, "coding")
        if decision:
            stdscr.addstr(3, 0, f"  Project:  {decision.project}", curses.color_pair(pairs["text"]))
            stdscr.addstr(4, 0, f"  Domain:   {decision.domain}", curses.color_pair(pairs["text"]))
            stdscr.addstr(5, 0, f"  Task:     {decision.task_type}", curses.color_pair(pairs["text"]))
            stdscr.addstr(6, 0, f"  Model:    {decision.model}", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
            stdscr.addstr(7, 0, f"  Endpoint: {decision.endpoint}", curses.color_pair(pairs["text"]))
            stdscr.addstr(8, 0, f"  Latency:  {decision.expected_latency_ms:.1f}ms", curses.color_pair(pairs["text"]))
            stdscr.addstr(9, 0, f"  Reason:   {decision.reason}", curses.color_pair(pairs["text"]))
            stdscr.addstr(10, 0, f"  Chain:    {' -> '.join(decision.chain)}", curses.color_pair(pairs["text"]))
        else:
            stdscr.addstr(3, 0, "  No routing decision available", curses.color_pair(pairs["warn"]))

    elif selection == 4:  # Kilo
        stdscr.addstr(0, 0, "KILO PROBE", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        projects = DATA.get_projects()
        proj_name = projects[0] if projects else "wsb-alpha"
        result = DATA.run_probe(proj_name, "probe-001", "Test probe")
        ok = result.get('confidence', 0) > 0 or ("error" not in result and "model_id" in result)
        status_pair = pairs["success"] if ok else pairs["error"]
        stdscr.addstr(3, 0, f"  Status: {'SUCCESS' if ok else 'FAILED'}", curses.color_pair(status_pair) | curses.A_BOLD)
        if "model_id" in result:
            stdscr.addstr(4, 0, f"  Model:  {result.get('model_id')}", curses.color_pair(pairs["text"]))
        if "text" in result:
            stdscr.addstr(5, 0, f"  Output: {str(result.get('text'))[:60]}", curses.color_pair(pairs["text"]))
        if "error" in result:
            stdscr.addstr(5, 0, f"  Error:  {result.get('error')}", curses.color_pair(pairs["error"]))

    elif selection == 5:  # Skills
        projects = DATA.get_projects()
        proj_name = projects[0] if projects else "wsb-alpha"
        stdscr.addstr(0, 0, f"SKILLS ({proj_name})", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        skills = DATA.get_skills(proj_name)
        if skills:
            for i, s in enumerate(skills[:12]):
                if 3 + i >= height - 3:
                    break
                if hasattr(s, "identity"):
                    stdscr.addstr(3 + i, 0, f"  {s.identity} v{s.version}", curses.color_pair(pairs["text"]))
                else:
                    stdscr.addstr(3 + i, 0, f"  {s}", curses.color_pair(pairs["text"]))
        else:
            stdscr.addstr(3, 0, "  No skills registered", curses.color_pair(pairs["warn"]))

    elif selection == 6:  # Benchmark
        stdscr.addstr(0, 0, "BENCHMARK", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        stdscr.addstr(3, 0, "Running latency benchmarks...", curses.color_pair(pairs["warn"]))
        stdscr.refresh()
        
        try:
            def dummy_task(x):
                import time
                time.sleep(0.001)
                return x * 2
            
            bench = run_benchmark(
                lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
                BenchmarkConfig(iterations=10, warmup=2),
                "parallel_executor_100_tasks"
            )
            stdscr.addstr(5, 0, f"Parallel Executor (100 tasks):", curses.color_pair(pairs["accent"]))
            stdscr.addstr(6, 0, f"  p50={bench.latency_ms['p50']:.1f}ms  p95={bench.latency_ms['p95']:.1f}ms  p99={bench.latency_ms['p99']:.1f}ms", curses.color_pair(pairs["text"]))
            stdscr.addstr(7, 0, f"  Throughput: {bench.throughput_per_s:.1f}/s  Errors: {bench.error_rate:.2%}", curses.color_pair(pairs["success"]))
        except Exception as e:
            stdscr.addstr(5, 0, f"Benchmark error: {e}", curses.color_pair(pairs["error"]))

    elif selection == 7:  # Logs
        stdscr.addstr(0, 0, "J5 HARNESS LOGS", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        sample_logs = [
            ("INFO", "System event: heartbeat", "success"),
            ("INFO", "Router initialized for wsb-alpha and burgonomics", "success"),
            ("WARN", "System event: slow probe response on nemotron", "warn"),
            ("ERROR", "Probe failed on endpoint backup: connection timeout", "error"),
            ("INFO", "Kilo inbox watcher registered 0 pending tasks", "success"),
            ("INFO", "Latency cache warmup completed (1000 keys)", "success"),
            ("WARN", "Rate limit headroom low on shared Zen IP bucket", "warn"),
            ("INFO", "Delegation ledger verified integrity", "success"),
        ]
        for i, (level, msg, p_name) in enumerate(sample_logs):
            if 3 + i >= height - 3:
                break
            stdscr.addstr(3 + i, 0, f"[{level}]", curses.color_pair(pairs[p_name]) | curses.A_BOLD)
            stdscr.addstr(3 + i, 8, f" {msg}", curses.color_pair(pairs["text"]))

    elif selection == 8:  # Config
        stdscr.addstr(0, 0, "CONFIGURATION", curses.color_pair(pairs["accent"]) | curses.A_BOLD)
        stdscr.addstr(1, 0, "=" * max(1, width - 1), curses.color_pair(pairs["text"]))
        try:
            cfg = load_config()
            lines = json.dumps(cfg, indent=2).splitlines()
            for i, line in enumerate(lines):
                if 3 + i >= height - 3:
                    break
                stdscr.addstr(3 + i, 0, line[:max(1, width - 1)], curses.color_pair(pairs["text"]))
        except Exception as e:
            stdscr.addstr(3, 0, f"Error loading config: {e}", curses.color_pair(pairs["error"]))
    
    footer_y = max(0, height - 2)
    stdscr.addstr(footer_y, 0, "Press any key to return to menu..."[:width - 1], curses.color_pair(pairs["accent"]))
    stdscr.refresh()
    stdscr.getch()


# ---------------------------------------------------------------------------
# ANSI Terminal UI fallback (Windows stdlib-only without curses)
# ---------------------------------------------------------------------------

def run_ansi_tui() -> None:
    """Stdlib-only ANSI terminal UI fallback for Windows and headless systems."""
    menu_items = [
        ("1", "Dashboard", "System overview, projects, tracked models"),
        ("2", "Projects", "Project list, domains, directories"),
        ("3", "Domains", "Domain specifications and tools"),
        ("4", "Routing", "Simulate model routing decision"),
        ("5", "Kilo Probe", "Run Kilo probe round-trip"),
        ("6", "Skills", "List ecosystem skills"),
        ("7", "Benchmark", "Execute latency benchmarks"),
        ("8", "Logs", "View system event logs"),
        ("9", "Config", "Inspect reliability configuration"),
        ("q", "Quit", "Exit J5 Harness TUI"),
    ]
    
    while True:
        # Clear screen
        print("\033[2J\033[H", end="")
        
        print(title("=== J5 HARNESS TUI (ANSI Mode) ==="))
        print(separator())
        for key, name, desc in menu_items:
            print(f"  {color(f'[{key}]', ANSI.ACCENT)} {color(name, ANSI.BOLD):<14} {color(desc, ANSI.MUTED)}")
        print(separator())
        
        try:
            choice = input(f"{color('Select option [1-9, q]:', ANSI.ACCENT)} ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break
        
        if choice in ("q", "quit", "exit"):
            break
        elif choice == "1":
            print(title("\n--- DASHBOARD ---"))
            status = DATA.get_global_status()
            projects_dict = status.get('projects', {})
            print(f"Projects:       {len(projects_dict)}")
            print(f"Models tracked: {len(status.get('shared_health', {}))}")
            print(f"Models scored:  {len(status.get('shared_scores', {}))}")
            for name, proj_status in projects_dict.items():
                domain = proj_status.get('domain', 'unknown')
                in_flight = proj_status.get('in_flight', 0)
                max_flight = proj_status.get('max_in_flight', 1)
                quarantined = proj_status.get('quarantined', [])
                q_text = ", ".join(quarantined) if quarantined else "none"
                print(f"\n  {color(name, ANSI.ACCENT)} ({domain}):")
                print(f"    In-flight:   {in_flight}/{max_flight}")
                print(f"    Quarantined: {q_text}")
        elif choice == "2":
            print(title("\n--- PROJECTS ---"))
            for p in DATA.get_projects():
                proj = DATA.project_registry.get_project(p) if DATA.project_registry else None
                status_str = color("enabled", ANSI.SUCCESS) if (proj and proj.enabled) else color("disabled", ANSI.WARNING)
                domain_str = proj.domain if proj else "unknown"
                dir_str = proj.project_dir if proj else ""
                print(f"  {color(p, ANSI.ACCENT):<16} [{domain_str}] {status_str}  {color(dir_str, ANSI.MUTED)}")
        elif choice == "3":
            print(title("\n--- DOMAINS ---"))
            for d in DATA.get_domains():
                dom = DATA.domain_registry.get_domain(d) if DATA.domain_registry else None
                desc = dom.description[:50] if dom else ""
                print(f"  {color(d, ANSI.ACCENT):<12}: {desc}")
        elif choice == "4":
            print(title("\n--- ROUTING DECISION ---"))
            projects = DATA.get_projects()
            proj_name = projects[0] if projects else "wsb-alpha"
            decision = DATA.get_routing_decision(proj_name, "coding")
            if decision:
                print(f"  {color('Project:', ANSI.ACCENT)}  {decision.project}")
                print(f"  {color('Domain:', ANSI.ACCENT)}   {decision.domain}")
                print(f"  {color('Task:', ANSI.ACCENT)}     {decision.task_type}")
                print(f"  {color('Model:', ANSI.ACCENT)}    {color(decision.model, ANSI.SUCCESS)}")
                print(f"  {color('Endpoint:', ANSI.ACCENT)} {decision.endpoint}")
                print(f"  {color('Latency:', ANSI.ACCENT)}  {decision.expected_latency_ms:.1f}ms")
                print(f"  {color('Reason:', ANSI.ACCENT)}   {decision.reason}")
                print(f"  {color('Chain:', ANSI.ACCENT)}    {' -> '.join(decision.chain)}")
            else:
                print(color("  No routing decision available", ANSI.WARNING))
        elif choice == "5":
            print(title("\n--- KILO PROBE ---"))
            projects = DATA.get_projects()
            proj_name = projects[0] if projects else "wsb-alpha"
            result = DATA.run_probe(proj_name, "probe-001", "Test probe")
            ok = result.get('confidence', 0) > 0 or ("error" not in result and "model_id" in result)
            status_line = color("SUCCESS", ANSI.SUCCESS) if ok else color("FAILED", ANSI.ERROR)
            print(f"  Status: {status_line}")
            if "model_id" in result:
                print(f"  Model:  {result.get('model_id')}")
            if "text" in result:
                print(f"  Output: {str(result.get('text'))[:60]}")
            if "error" in result:
                print(f"  Error:  {color(str(result.get('error')), ANSI.ERROR)}")
        elif choice == "6":
            projects = DATA.get_projects()
            proj_name = projects[0] if projects else "wsb-alpha"
            print(title(f"\n--- SKILLS ({proj_name}) ---"))
            skills = DATA.get_skills(proj_name)
            if skills:
                for s in skills[:15]:
                    if hasattr(s, "identity"):
                        print(f"  {color(s.identity, ANSI.ACCENT)} v{s.version}")
                    else:
                        print(f"  {color(str(s), ANSI.ACCENT)}")
            else:
                print(color("  No skills registered", ANSI.WARNING))
        elif choice == "7":
            print(title("\n--- BENCHMARK ---"))
            print(color("Running latency benchmarks...", ANSI.WARNING))
            try:
                def dummy_task(x):
                    import time
                    time.sleep(0.001)
                    return x * 2
                
                bench = run_benchmark(
                    lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
                    BenchmarkConfig(iterations=10, warmup=2),
                    "parallel_executor_100_tasks"
                )
                print(f"\n{color('Parallel Executor (100 tasks):', ANSI.ACCENT)}")
                print(f"  p50={bench.latency_ms['p50']:.1f}ms  p95={bench.latency_ms['p95']:.1f}ms  p99={bench.latency_ms['p99']:.1f}ms")
                print(f"  Throughput: {color(f'{bench.throughput_per_s:.1f}/s', ANSI.SUCCESS)}  Errors: {bench.error_rate:.2%}")
            except Exception as e:
                print(color(f"Benchmark error: {e}", ANSI.ERROR))
        elif choice == "8":
            print(title("\n--- LOGS ---"))
            sample_logs = [
                (ANSI.SUCCESS, "INFO", "System event: heartbeat"),
                (ANSI.SUCCESS, "INFO", "Router initialized for wsb-alpha and burgonomics"),
                (ANSI.WARNING, "WARN", "System event: slow probe response on nemotron"),
                (ANSI.ERROR, "ERROR", "Probe failed on endpoint backup: connection timeout"),
                (ANSI.SUCCESS, "INFO", "Kilo inbox watcher registered 0 pending tasks"),
                (ANSI.SUCCESS, "INFO", "Latency cache warmup completed (1000 keys)"),
                (ANSI.WARNING, "WARN", "Rate limit headroom low on shared Zen IP bucket"),
                (ANSI.SUCCESS, "INFO", "Delegation ledger verified integrity"),
            ]
            for ansi_code, level, msg in sample_logs:
                print(f"  {color(f'[{level}]', ansi_code):<18} {msg}")
        elif choice == "9":
            print(title("\n--- CONFIGURATION ---"))
            try:
                cfg = load_config()
                print(json.dumps(cfg, indent=2))
            except Exception as e:
                print(color(f"Error loading config: {e}", ANSI.ERROR))
        else:
            print(color(f"Unknown option '{choice}'. Please select 1-9 or q.", ANSI.WARNING))
        
        try:
            input(f"\n{color('Press Enter to return to menu...', ANSI.MUTED)}")
        except (EOFError, KeyboardInterrupt):
            break


# ---------------------------------------------------------------------------
# TUI Entry point
# ---------------------------------------------------------------------------

def run_tui() -> None:
    """Run the appropriate TUI based on availability."""
    if TEXTUAL_AVAILABLE:
        app = J5TUIApp()
        app.run()
    elif CURSES_AVAILABLE and wrapper is not None:
        wrapper(run_curses_tui)
    else:
        run_ansi_tui()


if __name__ == "__main__":
    run_tui()