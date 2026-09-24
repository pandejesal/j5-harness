#!/usr/bin/env python3
"""J5 Harness Modern Desktop — PyQt5 command center.

A T3-style control surface for the J5 Harness: sidebar navigation, command
palette (Ctrl+K), hero composer for task delegation, metric cards, and
management views for projects, domains, routing, delegation, Kilo probes,
skills, benchmarks, config and logs.

Design language (T3-inspired):
- near-black background (#09090b), elevated panels (#101014 / #17171c)
- 1px subtle borders (#232329), 10-14px radii, generous whitespace
- violet accent (#8b5cf6), zinc text (#f4f4f5 / #a1a1aa / #63636b)
- text-first navigation (no emoji icons), Inter / Segoe UI typography

Backend access is fully defensive: every tools.* call is wrapped so the UI
always opens, even if the harness backend fails. Failures surface as inline
error states, never as a startup crash.

Usage:
    python j5_desktop/modern_app.py            # launch the app
    python j5_desktop/modern_app.py --smoke    # offscreen build check, exit 0
"""

from __future__ import annotations

import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_VERSION = "2.0.0-modern"

# ---------------------------------------------------------------------------
# Backend adapter (defensive: never raises, always returns (ok, payload))
# ---------------------------------------------------------------------------


@dataclass
class BackendResult:
    ok: bool
    payload: object = None
    error: str = ""


class Backend:
    """Thin defensive wrapper over the harness Python APIs."""

    def __init__(self) -> None:
        self._log: list[str] = []
        self._multi_router = None
        self._domain_registry = None
        self._project_registry = None
        self._config: dict = {}
        self._config_error = ""
        self._boot_error = ""
        self.refresh()

    # -- logging ---------------------------------------------------------
    def log(self, message: str) -> None:
        self._log.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    def logs(self) -> list[str]:
        return list(self._log)

    # -- boot ------------------------------------------------------------
    def refresh(self) -> None:
        try:
            from tools.domains import DomainRegistry, ProjectRegistry, MultiProjectRouter
            from tools.harness.integration import load_config

            self._config = load_config()
            self._domain_registry = DomainRegistry()
            self._project_registry = ProjectRegistry()
            self._multi_router = MultiProjectRouter()
            self._boot_error = ""
            self.log("Backend connected: config + registries + router loaded")
        except Exception as exc:  # noqa: BLE001 - surfaced in UI, never raised
            self._boot_error = f"{type(exc).__name__}: {exc}"
            self.log(f"Backend boot failed: {self._boot_error}")

    @property
    def connected(self) -> bool:
        return not self._boot_error

    @property
    def boot_error(self) -> str:
        return self._boot_error

    # -- overview --------------------------------------------------------
    def overview(self) -> BackendResult:
        try:
            projects = self._project_registry.list_projects()
            domains = self._domain_registry.list_domains()
            status = self._multi_router.global_status()
            return BackendResult(True, {
                "projects": projects,
                "domains": domains,
                "status": status,
            })
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    def project_names(self) -> list[str]:
        try:
            return list(self._project_registry.list_projects())
        except Exception:  # noqa: BLE001
            return []

    def domain_names(self) -> list[str]:
        try:
            return list(self._domain_registry.list_domains())
        except Exception:  # noqa: BLE001
            return []

    def project_detail(self, name: str) -> BackendResult:
        try:
            proj = self._project_registry.get_project(name)
            ladders = getattr(proj, "custom_fallback_ladders", {}) or {}
            try:
                skills = list(proj.get_all_skills())
            except Exception:  # noqa: BLE001
                skills = []
            try:
                tools = list(proj.get_all_tools())
            except Exception:  # noqa: BLE001
                tools = []
            return BackendResult(True, {
                "name": getattr(proj, "name", name),
                "domain": getattr(proj, "domain", "-"),
                "enabled": bool(getattr(proj, "enabled", False)),
                "directory": str(getattr(proj, "project_dir", "-")),
                "ladders": {k: list(v) for k, v in ladders.items()},
                "skills": skills,
                "tools": tools,
            })
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    def domain_detail(self, name: str) -> BackendResult:
        try:
            dom = self._domain_registry.get_domain(name)
            models = getattr(dom, "models", None)
            return BackendResult(True, {
                "name": getattr(dom, "name", name),
                "description": getattr(dom, "description", ""),
                "primary": list(getattr(models, "primary", []) or []),
                "fallback": list(getattr(models, "fallback", []) or []),
                "skills": list(getattr(dom, "skills", []) or []),
                "tools": list(getattr(dom, "tools", []) or []),
                "data_sources": list(getattr(dom, "data_sources", []) or []),
                "ladders": {k: list(v) for k, v in (getattr(dom, "fallback_ladders", {}) or {}).items()},
            })
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    # -- routing ---------------------------------------------------------
    def pick(self, project: str, task_type: str) -> BackendResult:
        try:
            decision = self._multi_router.pick(project, task_type)
            return BackendResult(True, {
                "project": getattr(decision, "project", project),
                "domain": getattr(decision, "domain", "-"),
                "task_type": getattr(decision, "task_type", task_type),
                "model": getattr(decision, "model", "?"),
                "endpoint": getattr(decision, "endpoint", "-"),
                "expected_latency_ms": float(getattr(decision, "expected_latency_ms", 0.0) or 0.0),
                "reason": getattr(decision, "reason", ""),
                "chain": list(getattr(decision, "chain", []) or []),
            })
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    # -- delegation ------------------------------------------------------
    def delegate(self, project: str, task_type: str, prompt: str, task_id: str) -> BackendResult:
        """Decompose a single-leaf DAG and run it through the real router_fn."""
        try:
            from tools.delegation.ledger import DelegationLedger
            from tools.delegation.orchestrator import Orchestrator
            from tools.harness.integration import SHARED, build_project_contexts, make_router_fn

            config = dict(self._config)
            contexts = {c.name: c for c in build_project_contexts(config, "coder")}
            if project not in contexts:
                return BackendResult(False, error=f"unknown project {project!r}")
            ctx = contexts[project]
            ledger = DelegationLedger(ctx.ledger_path)
            router_fn = make_router_fn(ctx, SHARED, config)
            orch = Orchestrator(ledger=ledger, router_fn=router_fn)
            dag = orch.decompose(prompt, [{"task_id": task_id, "prompt": prompt}])
            dag = orch.run(dag, task_type=task_type)
            node = dag.nodes[task_id]
            self.log(f"Delegated {task_id} -> {project} [{task_type}] via {node.model_id} ({node.confidence:.2f})")
            return BackendResult(True, {
                "task_id": task_id,
                "state": node.state.name,
                "model_id": node.model_id,
                "confidence": float(node.confidence or 0.0),
                "text": (node.result or "")[:4000],
                "session_id": getattr(node, "session_id", None),
                "usage": getattr(node, "usage", None) or {},
                "ledger": str(ctx.ledger_path),
            })
        except Exception as exc:  # noqa: BLE001
            self.log(f"Delegation failed: {exc}")
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}\n{traceback.format_exc(limit=3)}")

    # -- kilo ------------------------------------------------------------
    def probe(self, project: str, probe_id: str, prompt: str) -> BackendResult:
        try:
            from tools.harness.integration import build_project_contexts, run_probe_roundtrip

            config = dict(self._config)
            contexts = {c.name: c for c in build_project_contexts(config, "coder")}
            if project not in contexts:
                return BackendResult(False, error=f"unknown project {project!r}")
            kilo_cfg = config.get("kilo", {})
            if not kilo_cfg:
                return BackendResult(False, error="kilo section missing from reliability.config.json")
            result = run_probe_roundtrip(contexts[project], probe_id, prompt, kilo_cfg)
            self.log(f"Probe {probe_id} -> {result.get('model_id')} ({result.get('confidence')})")
            return BackendResult(True, result)
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    def watcher_once(self) -> BackendResult:
        try:
            from tools.harness.watch_kilo import process_once as watch_once

            out = watch_once()
            self.log("Kilo watcher cycle completed")
            return BackendResult(True, {"result": str(out)})
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    # -- skills ----------------------------------------------------------
    def skills(self, project: str, query: str = "") -> BackendResult:
        try:
            from tools.domains import load_project_config
            from tools.skills.ecosystem import SkillHub

            proj = load_project_config(project)
            hub = SkillHub(roots=[Path(r) for r in proj.get_all_skills()])
            items = hub.list_skills()
            rows = []
            for s in items:
                identity = str(getattr(s, "identity", s))
                if query and query.lower() not in identity.lower():
                    continue
                rows.append({
                    "identity": identity,
                    "version": str(getattr(s, "version", "-")),
                    "source": str(getattr(s, "source", "-")),
                })
            return BackendResult(True, rows)
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    # -- benchmarks ------------------------------------------------------
    def bench_quick(self) -> BackendResult:
        try:
            from tools.latency.benchmark import BenchmarkConfig, run_benchmark
            from tools.latency.caching import CacheConfig, MultiTierCache
            from tools.latency.parallel_executor import run_parallel

            def dummy_task(x: int) -> int:
                time.sleep(0.001)
                return x * 2

            bench = run_benchmark(
                lambda: run_parallel(dummy_task, list(range(60)), max_workers=4),
                BenchmarkConfig(iterations=5, warmup=1),
                "parallel_executor_60_tasks",
            )
            cache = MultiTierCache(CacheConfig(l1_max_entries=10000, enable_l2=False))
            for i in range(500):
                cache.set(f"key{i}", f"value{i}")
            bench2 = run_benchmark(
                lambda: [cache.get(f"key{i}") for i in range(60)],
                BenchmarkConfig(iterations=10, warmup=2),
                "cache_get_60_keys",
            )
            return BackendResult(True, [
                {"name": bench.name, "p50": bench.latency_ms["p50"],
                 "p95": bench.latency_ms["p95"], "throughput": bench.throughput_per_s},
                {"name": bench2.name, "p50": bench2.latency_ms["p50"],
                 "p95": bench2.latency_ms["p95"], "throughput": bench2.throughput_per_s},
            ])
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    # -- config ----------------------------------------------------------
    def config_path(self) -> Path:
        return PROJECT_ROOT / "tools" / "reliability" / "reliability.config.json"

    def config_text(self) -> BackendResult:
        try:
            return BackendResult(True, self.config_path().read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")

    def config_save(self, text: str) -> BackendResult:
        try:
            parsed = json.loads(text)  # validate first; never write invalid JSON
            self.config_path().write_text(json.dumps(parsed, indent=2), encoding="utf-8")
            self._config = parsed
            self.log("reliability.config.json saved")
            return BackendResult(True, {"projects": list(parsed.get("projects", {}).keys())})
        except json.JSONDecodeError as exc:
            return BackendResult(False, error=f"Invalid JSON: {exc}")
        except Exception as exc:  # noqa: BLE001
            return BackendResult(False, error=f"{type(exc).__name__}: {exc}")


# ---------------------------------------------------------------------------
# Qt imports (after backend so --help style paths never break on missing Qt)
# ---------------------------------------------------------------------------

from PyQt5.QtCore import QObject, QRunnable, QThreadPool, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QFont, QKeySequence
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMainWindow, QPlainTextEdit, QPushButton, QShortcut, QSplitter, QStackedWidget,
    QStatusBar, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout,
    QWidget, QHeaderView, QAbstractItemView, QSizePolicy,
)

# ---------------------------------------------------------------------------
# Theme (T3-inspired dark)
# ---------------------------------------------------------------------------

C_BG = "#09090b"
C_PANEL = "#101014"
C_ELEV = "#17171c"
C_HOVER = "#1e1e24"
C_BORDER = "#232329"
C_BORDER_SOFT = "#1a1a1f"
C_TEXT = "#f4f4f5"
C_MUTED = "#a1a1aa"
C_DIM = "#63636b"
C_ACCENT = "#8b5cf6"
C_ACCENT_HOVER = "#7c3aed"
C_SUCCESS = "#34d399"
C_WARN = "#fbbf24"
C_ERROR = "#f87171"
C_INFO = "#60a5fa"

QSS = f"""
* {{ outline: none; }}
QMainWindow, QWidget#root {{ background: {C_BG}; color: {C_TEXT}; }}
QWidget {{ font-family: "Inter", "Segoe UI", sans-serif; font-size: 13px; }}

/* Sidebar */
QWidget#sidebar {{ background: {C_PANEL}; border-right: 1px solid {C_BORDER_SOFT}; }}
QLabel#brand {{ font-size: 17px; font-weight: 800; letter-spacing: 0.5px; }}
QLabel#brandSub {{ color: {C_DIM}; font-size: 11px; }}
QPushButton#navBtn {{
    background: transparent; color: {C_MUTED}; border: none; border-radius: 8px;
    padding: 9px 12px; text-align: left; font-size: 13px;
}}
QPushButton#navBtn:hover {{ background: {C_HOVER}; color: {C_TEXT}; }}
QPushButton#navBtn:checked {{ background: {C_ELEV}; color: {C_TEXT}; border: 1px solid {C_BORDER}; }}
QPushButton#ctaBtn {{
    background: {C_ACCENT}; color: white; border: none; border-radius: 9px;
    padding: 10px 12px; font-weight: 700; font-size: 13px;
}}
QPushButton#ctaBtn:hover {{ background: {C_ACCENT_HOVER}; }}

/* Topbar */
QWidget#topbar {{ background: {C_BG}; border-bottom: 1px solid {C_BORDER_SOFT}; }}
QLabel#viewTitle {{ font-size: 15px; font-weight: 700; }}
QPushButton#ghostBtn {{
    background: {C_PANEL}; color: {C_MUTED}; border: 1px solid {C_BORDER};
    border-radius: 8px; padding: 6px 12px; font-size: 12px;
}}
QPushButton#ghostBtn:hover {{ color: {C_TEXT}; border-color: #34343c; }}

/* Cards */
QFrame#card {{
    background: {C_PANEL}; border: 1px solid {C_BORDER};
    border-radius: 12px;
}}
QLabel#metricValue {{ font-size: 26px; font-weight: 800; }}
QLabel#metricLabel {{ color: {C_MUTED}; font-size: 12px; }}
QLabel#muted {{ color: {C_MUTED}; }}
QLabel#dim {{ color: {C_DIM}; font-size: 12px; }}
QLabel#h2 {{ font-size: 14px; font-weight: 700; }}

/* Inputs */
QLineEdit, QTextEdit#composer, QPlainTextEdit {{
    background: {C_ELEV}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 10px; padding: 9px 11px; selection-background-color: #3b2d6e;
}}
QLineEdit:focus, QTextEdit#composer:focus {{ border: 1px solid {C_ACCENT}; }}
QTextEdit#composer {{ font-size: 14px; }}
QComboBox {{
    background: {C_PANEL}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 8px; padding: 6px 10px;
}}
QComboBox QAbstractItemView {{ background: {C_ELEV}; color: {C_TEXT}; selection-background-color: #2a2145; border: 1px solid {C_BORDER}; }}
QPushButton#chipBtn {{
    background: transparent; color: {C_MUTED}; border: 1px solid {C_BORDER};
    border-radius: 14px; padding: 5px 13px; font-size: 12px;
}}
QPushButton#chipBtn:checked {{ background: #221d38; color: {C_TEXT}; border: 1px solid {C_ACCENT}; }}
QPushButton#sendBtn {{
    background: {C_ACCENT}; color: white; border: none;
    border-radius: 10px; padding: 10px 22px; font-weight: 700;
}}
QPushButton#sendBtn:hover {{ background: {C_ACCENT_HOVER}; }}
QPushButton#sendBtn:disabled {{ background: {C_ELEV}; color: {C_DIM}; }}

/* Tables */
QTableWidget {{
    background: {C_PANEL}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 10px; gridline-color: {C_BORDER_SOFT}; font-size: 12.5px;
}}
QTableWidget::item {{ padding: 6px; }}
QTableWidget::item:selected {{ background: #221d38; color: {C_TEXT}; }}
QHeaderView::section {{
    background: {C_ELEV}; color: {C_MUTED}; border: none;
    padding: 8px; font-weight: 600; font-size: 12px;
}}

/* Lists */
QListWidget {{
    background: {C_PANEL}; color: {C_TEXT}; border: 1px solid {C_BORDER};
    border-radius: 10px; padding: 4px; font-size: 12.5px;
}}
QListWidget::item {{ padding: 7px 9px; border-radius: 7px; }}
QListWidget::item:selected {{ background: #221d38; }}
QListWidget::item:hover {{ background: {C_HOVER}; }}

/* Scrollbars */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #2c2c33; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #3a3a42; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #2c2c33; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Status bar */
QStatusBar {{ background: {C_PANEL}; color: {C_MUTED}; border-top: 1px solid {C_BORDER_SOFT}; font-size: 12px; }}
QSplitter::handle {{ background: {C_BORDER_SOFT}; }}
QCheckBox {{ color: {C_MUTED}; spacing: 8px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {C_BORDER}; background: {C_ELEV}; }}
QCheckBox::indicator:checked {{ background: {C_ACCENT}; border: 1px solid {C_ACCENT}; }}
QDialog {{ background: {C_PANEL}; border: 1px solid {C_BORDER}; border-radius: 12px; }}
"""

# ---------------------------------------------------------------------------
# Background jobs (never block the GUI thread)
# ---------------------------------------------------------------------------


class JobSignals(QObject):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)


class Job(QRunnable):
    def __init__(self, fn, *args, **kwargs) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = JobSignals()

    def run(self) -> None:
        try:
            self.signals.done.emit(self.fn(*self.args, **self.kwargs))
        except Exception as exc:  # noqa: BLE001
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")


def run_job(pool: QThreadPool, fn, on_done, on_error=None, *args, **kwargs) -> None:
    job = Job(fn, *args, **kwargs)
    job.signals.done.connect(on_done)
    if on_error is not None:
        job.signals.failed.connect(on_error)
    else:
        job.signals.failed.connect(lambda e: on_done(BackendResult(False, error=e)))
    pool.start(job)


# ---------------------------------------------------------------------------
# Small building blocks
# ---------------------------------------------------------------------------


def vbox(*widgets: QWidget, spacing: int = 10, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for w in widgets:
        layout.addWidget(w)
    return layout


def hbox(*widgets: QWidget, spacing: int = 10, margins: tuple[int, int, int, int] = (0, 0, 0, 0)) -> QHBoxLayout:
    layout = QHBoxLayout()
    layout.setSpacing(spacing)
    layout.setContentsMargins(*margins)
    for w in widgets:
        layout.addWidget(w)
    return layout


def muted_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


def section_title(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("h2")
    return lbl


class MetricCard(QFrame):
    def __init__(self, label: str, value: str = "-", accent: str = C_TEXT, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self._value = QLabel(value)
        self._value.setObjectName("metricValue")
        self._value.setStyleSheet(f"color: {accent};")
        lbl = QLabel(label)
        lbl.setObjectName("metricLabel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        layout.addWidget(self._value)
        layout.addWidget(lbl)

    def set_value(self, value: str) -> None:
        self._value.setText(value)


def fill_table(table: QTableWidget, columns: list[str], rows: list[list[str]]) -> None:
    table.clear()
    table.setColumnCount(len(columns))
    table.setRowCount(len(rows))
    table.setHorizontalHeaderLabels(columns)
    for r, row in enumerate(rows):
        for c, val in enumerate(row):
            item = QTableWidgetItem(str(val))
            item.setFlags(item.flags() ^ Qt.ItemIsEditable)
            table.setItem(r, c, item)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.Stretch)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.verticalHeader().setVisible(False)


# ---------------------------------------------------------------------------
# Command palette (Ctrl+K)
# ---------------------------------------------------------------------------


class Palette(QDialog):
    def __init__(self, actions: list[tuple[str, str]], parent=None) -> None:
        super().__init__(parent)
        self.actions = actions
        self.chosen: tuple[str, str] | None = None
        self.setWindowTitle("Command palette")
        self.setModal(True)
        self.resize(520, 380)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Type a command…")
        self.filter.textChanged.connect(self._apply_filter)
        self.list = QListWidget(self)
        self.list.itemActivated.connect(lambda _item: self.accept())
        layout.addWidget(self.filter)
        layout.addWidget(self.list)
        self._apply_filter("")
        self.filter.setFocus()

    def _apply_filter(self, text: str) -> None:
        self.list.clear()
        q = text.lower()
        for group, label in self.actions:
            if q in label.lower() or q in group.lower():
                QListWidgetItem(f"{group}  ·  {label}", self.list)
        if self.list.count():
            self.list.setCurrentRow(0)

    def accept(self) -> None:  # noqa: D102
        item = self.list.currentItem()
        if item is not None:
            text = item.text()
            for group, label in self.actions:
                if text == f"{group}  ·  {label}":
                    self.chosen = (group, label)
                    break
        super().accept()


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------


class CommandView(QWidget):
    """Hero composer + metrics + activity feed."""

    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(18)

        hero = QLabel("What should the swarm do?")
        hero.setStyleSheet("font-size: 24px; font-weight: 800;")
        root.addWidget(hero)
        root.addWidget(muted_label("Describe a task. J5 picks the domain, model and worker pool, then verifies the result."))

        # Composer card
        composer_card = QFrame()
        composer_card.setObjectName("card")
        cl = QVBoxLayout(composer_card)
        cl.setContentsMargins(16, 16, 16, 16)
        cl.setSpacing(12)
        self.prompt = QTextEdit()
        self.prompt.setObjectName("composer")
        self.prompt.setPlaceholderText("e.g. Backtest a momentum strategy on NIFTY with walk-forward validation…")
        self.prompt.setFixedHeight(96)
        cl.addWidget(self.prompt)

        chip_row = QHBoxLayout()
        chip_row.setSpacing(8)
        self.chips = QButtonGroup(self)
        self.chips.setExclusive(True)
        self.task_type = "coding"
        for i, tt in enumerate(["coding", "research", "analysis", "conversation"]):
            btn = QPushButton(tt)
            btn.setObjectName("chipBtn")
            btn.setCheckable(True)
            btn.setChecked(i == 0)
            btn.clicked.connect(lambda _c, t=tt: setattr(self, "task_type", t))
            self.chips.addButton(btn, i)
            chip_row.addWidget(btn)
        chip_row.addStretch(1)
        self.send_btn = QPushButton("Delegate  ⏎")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.clicked.connect(self._send)
        chip_row.addWidget(self.send_btn)
        cl.addLayout(chip_row)
        root.addWidget(composer_card)

        # Metric cards
        cards = QHBoxLayout()
        cards.setSpacing(12)
        self.m_projects = MetricCard("Projects", "-", C_INFO)
        self.m_models = MetricCard("Models tracked", "-", C_ACCENT)
        self.m_scored = MetricCard("Models scored", "-", C_SUCCESS)
        self.m_inflight = MetricCard("In-flight", "-", C_WARN)
        for m in (self.m_projects, self.m_models, self.m_scored, self.m_inflight):
            m.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            cards.addWidget(m)
        root.addLayout(cards)

        # Activity
        root.addWidget(section_title("Activity"))
        self.feed = QListWidget()
        self.feed.setMinimumHeight(180)
        root.addWidget(self.feed, 1)

        send_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        send_shortcut.activated.connect(self._send)

    def refresh_metrics(self, overview: dict) -> None:
        status = overview.get("status", {}) or {}
        projects = status.get("projects", {}) or {}
        self.m_projects.set_value(str(len(overview.get("projects", []) or [])))
        self.m_models.set_value(str(len(status.get("shared_health", {}) or {})))
        self.m_scored.set_value(str(len(status.get("shared_scores", {}) or {})))
        total = sum((p.get("in_flight", 0) or 0) for p in projects.values())
        self.m_inflight.set_value(str(total))

    def add_feed(self, text: str) -> None:
        self.feed.insertItem(0, f"[{time.strftime('%H:%M:%S')}] {text}")

    def _send(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            return
        project = self.ctx.current_project()
        task_id = f"task-{int(time.time()) % 100000:05d}"
        self.send_btn.setEnabled(False)
        self.add_feed(f"Sending {task_id} to {project} [{self.task_type}]…")
        run_job(
            self.ctx.pool, self.ctx.backend.delegate,
            lambda res: self.ctx.on_delegated(res, prompt, task_id),
            lambda err: self.ctx.on_delegated(BackendResult(False, error=err), prompt, task_id),
            project, self.task_type, prompt, task_id,
        )
        self.prompt.clear()


class TableView(QWidget):
    """Projects / domains / skills table + detail pane."""

    def __init__(self, title: str, hint: str, columns: list[str], parent=None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title(title))
        root.addWidget(muted_label(hint))
        split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget()
        self.table.setMinimumWidth(420)
        split.addWidget(self.table)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setPlaceholderText("Select a row to inspect details…")
        self.detail.setMinimumWidth(280)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        root.addWidget(split, 1)
        self._columns = columns

    def set_rows(self, rows: list[list[str]]) -> None:
        fill_table(self.table, self._columns, rows)

    def set_detail(self, text: str) -> None:
        self.detail.setPlainText(text)


class RoutingView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Routing"))
        root.addWidget(muted_label("Ask the domain-aware router which model a task would land on. No dispatch happens here."))

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.task = QComboBox()
        self.task.addItems(["coding", "research", "analysis", "conversation"])
        self.go = QPushButton("Get decision")
        self.go.setObjectName("sendBtn")
        self.go.clicked.connect(self._ask)
        bar.addWidget(QLabel("Task type:"))
        bar.addWidget(self.task)
        bar.addWidget(self.go)
        bar.addStretch(1)
        root.addLayout(bar)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText("Routing decision will appear here…")
        root.addWidget(self.out, 1)

    def _ask(self) -> None:
        self.go.setEnabled(False)
        self.out.setPlainText("Routing…")
        run_job(
            self.ctx.pool, self.ctx.backend.pick,
            self._show, lambda e: self._show(BackendResult(False, error=e)),
            self.ctx.current_project(), self.task.currentText(),
        )

    def _show(self, res: BackendResult) -> None:
        self.go.setEnabled(True)
        if not res.ok:
            self.out.setPlainText(f"Routing failed:\n{res.error}")
            return
        d = res.payload
        chain = " → ".join(d["chain"]) if d["chain"] else "(empty)"
        self.out.setPlainText(
            f"Model:    {d['model']}\nDomain:   {d['domain']}\nEndpoint: {d['endpoint']}\n"
            f"Latency:  {d['expected_latency_ms']:.0f} ms (expected)\nReason:   {d['reason']}\n\n"
            f"Fallback chain:\n{chain}"
        )


class DelegationView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Delegation"))
        root.addWidget(muted_label("Dispatch a task through decompose → route → verify. Results land in the project ledger."))

        self.prompt = QTextEdit()
        self.prompt.setObjectName("composer")
        self.prompt.setPlaceholderText("Task prompt…")
        self.prompt.setFixedHeight(110)
        root.addWidget(self.prompt)

        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.task = QComboBox()
        self.task.addItems(["coding", "research", "analysis"])
        self.run_btn = QPushButton("Dispatch task")
        self.run_btn.setObjectName("sendBtn")
        self.run_btn.clicked.connect(self._run)
        bar.addWidget(QLabel("Task type:"))
        bar.addWidget(self.task)
        bar.addWidget(self.run_btn)
        bar.addStretch(1)
        root.addLayout(bar)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out, 1)

    def _run(self) -> None:
        prompt = self.prompt.toPlainText().strip()
        if not prompt:
            self.out.setPlainText("Prompt is empty.")
            return
        task_id = f"task-{int(time.time()) % 100000:05d}"
        self.run_btn.setEnabled(False)
        self.out.setPlainText(f"Dispatching {task_id}…")
        run_job(
            self.ctx.pool, self.ctx.backend.delegate,
            self._show, lambda e: self._show(BackendResult(False, error=e)),
            self.ctx.current_project(), self.task.currentText(), prompt, task_id,
        )

    def _show(self, res: BackendResult) -> None:
        self.run_btn.setEnabled(True)
        if not res.ok:
            self.out.setPlainText(f"Dispatch failed:\n{res.error}")
            return
        d = res.payload
        self.out.setPlainText(
            f"Task:       {d['task_id']}\nState:      {d['state']}\nModel:      {d['model_id']}\n"
            f"Confidence: {d['confidence']:.2f}\nLedger:     {d['ledger']}\n\nResult:\n{d['text']}"
        )


class KiloView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Kilo probes"))
        root.addWidget(muted_label("File-bus round-trip: probe markdown → bridge → receipt. Atomic writes, ledger-tracked."))

        form = QFrame()
        form.setObjectName("card")
        fl = QVBoxLayout(form)
        fl.setContentsMargins(16, 16, 16, 16)
        fl.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.probe_id = QLineEdit()
        self.probe_id.setText(f"probe-{int(time.time()) % 100000:05d}")
        self.probe_id.setPlaceholderText("probe id")
        self.prompt = QLineEdit()
        self.prompt.setText("Health check from J5 Harness")
        self.prompt.setPlaceholderText("prompt")
        self.run_btn = QPushButton("Run probe")
        self.run_btn.setObjectName("sendBtn")
        self.run_btn.clicked.connect(self._run)
        self.watch_btn = QPushButton("Run watcher once")
        self.watch_btn.setObjectName("ghostBtn")
        self.watch_btn.clicked.connect(self._watch)
        row.addWidget(QLabel("ID:"))
        row.addWidget(self.probe_id)
        row.addWidget(QLabel("Prompt:"))
        row.addWidget(self.prompt, 1)
        row.addWidget(self.run_btn)
        row.addWidget(self.watch_btn)
        fl.addLayout(row)
        root.addWidget(form)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out, 1)

    def _run(self) -> None:
        self.run_btn.setEnabled(False)
        self.out.setPlainText("Running probe…")
        run_job(
            self.ctx.pool, self.ctx.backend.probe,
            self._show, lambda e: self._show(BackendResult(False, error=e)),
            self.ctx.current_project(), self.probe_id.text().strip(), self.prompt.text(),
        )

    def _show(self, res: BackendResult) -> None:
        self.run_btn.setEnabled(True)
        self.out.setPlainText(json.dumps(res.payload if res.ok else {"error": res.error}, indent=2, default=str))

    def _watch(self) -> None:
        self.watch_btn.setEnabled(False)
        run_job(
            self.ctx.pool, self.ctx.backend.watcher_once,
            lambda r: (self.watch_btn.setEnabled(True),
                       self.out.setPlainText(json.dumps(r.payload if r.ok else {"error": r.error}, indent=2, default=str))),
            lambda e: (self.watch_btn.setEnabled(True), self.out.setPlainText(f"Watcher failed:\n{e}")),
        )


class SkillsView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Skills"))
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search skills…  (Enter to search)")
        self.search.returnPressed.connect(self._load)
        self.reload = QPushButton("Reload")
        self.reload.setObjectName("ghostBtn")
        self.reload.clicked.connect(self._load)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.reload)
        root.addLayout(bar)
        self.table = QTableWidget()
        root.addWidget(self.table, 1)

    def _load(self) -> None:
        run_job(
            self.ctx.pool, self.ctx.backend.skills,
            self._show, lambda e: fill_table(self.table, ["Error"], [[e]]),
            self.ctx.current_project(), self.search.text().strip(),
        )

    def _show(self, res: BackendResult) -> None:
        if not res.ok:
            fill_table(self.table, ["Error"], [[res.error]])
            return
        rows = [[r["identity"], r["version"], r["source"]] for r in res.payload]
        fill_table(self.table, ["Identity", "Version", "Source"], rows or [["(no skills found)", "", ""]])


class BenchView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Benchmarks"))
        root.addWidget(muted_label("Quick latency snapshot: parallel executor and multi-tier cache."))
        bar = QHBoxLayout()
        self.run_btn = QPushButton("Run quick benchmark")
        self.run_btn.setObjectName("sendBtn")
        self.run_btn.clicked.connect(self._run)
        bar.addWidget(self.run_btn)
        bar.addStretch(1)
        root.addLayout(bar)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out, 1)

    def _run(self) -> None:
        self.run_btn.setEnabled(False)
        self.out.setPlainText("Running…")
        run_job(self.ctx.pool, self.ctx.backend.bench_quick, self._show,
                lambda e: self._show(BackendResult(False, error=e)))

    def _show(self, res: BackendResult) -> None:
        self.run_btn.setEnabled(True)
        if not res.ok:
            self.out.setPlainText(f"Benchmark failed:\n{res.error}")
            return
        lines = []
        for b in res.payload:
            lines.append(f"{b['name']}\n  p50 {b['p50']:.2f} ms   p95 {b['p95']:.2f} ms   {b['throughput']:.0f}/s")
        self.out.setPlainText("\n\n".join(lines))


class ConfigView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        root.addWidget(section_title("Configuration"))
        root.addWidget(muted_label("reliability.config.json — validated before every save. Invalid JSON is never written."))
        self.editor = QPlainTextEdit()
        font = QFont("Cascadia Code", 11)
        self.editor.setFont(font)
        root.addWidget(self.editor, 1)
        bar = QHBoxLayout()
        bar.setSpacing(10)
        self.reload_btn = QPushButton("Reload")
        self.reload_btn.setObjectName("ghostBtn")
        self.reload_btn.clicked.connect(self._load)
        self.save_btn = QPushButton("Validate + save")
        self.save_btn.setObjectName("sendBtn")
        self.save_btn.clicked.connect(self._save)
        self.status = QLabel("")
        self.status.setObjectName("muted")
        bar.addWidget(self.reload_btn)
        bar.addWidget(self.save_btn)
        bar.addWidget(self.status, 1)
        root.addLayout(bar)
        self._load()

    def _load(self) -> None:
        res = self.ctx.backend.config_text()
        self.editor.setPlainText(res.payload if res.ok else f"# load failed:\n# {res.error}")
        self.status.setText(f"Loaded {self.ctx.backend.config_path().name}" if res.ok else "Load failed")

    def _save(self) -> None:
        res = self.ctx.backend.config_save(self.editor.toPlainText())
        if res.ok:
            self.status.setText(f"Saved — projects: {', '.join(res.payload['projects'])}")
            self.ctx.refresh_all()
        else:
            self.status.setText(res.error)


class LogsView(QWidget):
    def __init__(self, ctx: "AppCtx", parent=None) -> None:
        super().__init__(parent)
        self.ctx = ctx
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)
        head = QHBoxLayout()
        head.addWidget(section_title("Logs"))
        head.addStretch(1)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setObjectName("ghostBtn")
        self.clear_btn.clicked.connect(lambda: self.out.clear())
        self.copy_btn = QPushButton("Refresh")
        self.copy_btn.setObjectName("ghostBtn")
        self.copy_btn.clicked.connect(self.refresh)
        head.addWidget(self.clear_btn)
        head.addWidget(self.copy_btn)
        root.addLayout(head)
        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        root.addWidget(self.out, 1)
        self.refresh()

    def refresh(self) -> None:
        self.out.setPlainText("\n".join(self.ctx.backend.logs()) or "(no log entries yet)")


# ---------------------------------------------------------------------------
# Shared app context
# ---------------------------------------------------------------------------


@dataclass
class AppCtx:
    backend: Backend
    pool: QThreadPool
    project_combo: QComboBox = None  # type: ignore[assignment]
    status_project: QLabel = None  # type: ignore[assignment]
    status_flight: QLabel = None  # type: ignore[assignment]
    status_conn: QLabel = None  # type: ignore[assignment]
    on_delegated: object = None
    refresh_all: object = None

    def current_project(self) -> str:
        try:
            return self.project_combo.currentText() or "wsb-alpha"
        except Exception:  # noqa: BLE001
            return "wsb-alpha"


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

NAV = [
    ("command", "Command", "Delegate tasks to the swarm"),
    ("projects", "Projects", "Enabled projects and fallback ladders"),
    ("domains", "Domains", "Quant, finance, drone, research, coding, general"),
    ("routing", "Routing", "Model decisions without dispatch"),
    ("delegation", "Delegation", "Full decompose → route → verify runs"),
    ("kilo", "Kilo", "File-bus probes and watcher"),
    ("skills", "Skills", "Versioned skill registry browser"),
    ("bench", "Benchmarks", "Latency snapshots"),
    ("config", "Config", "reliability.config.json editor"),
    ("logs", "Logs", "Harness event log"),
]


class MainWindow(QMainWindow):
    def __init__(self, backend: Backend) -> None:
        super().__init__()
        self.backend = backend
        self.pool = QThreadPool.globalInstance()
        self.setWindowTitle("J5 Harness — Command Center")
        self.resize(1280, 820)
        self.setMinimumSize(1024, 680)

        self.ctx = AppCtx(backend=backend, pool=self.pool)
        self.ctx.on_delegated = self._on_delegated
        self.ctx.refresh_all = self.refresh_all

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        shell = QHBoxLayout(root)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        # -- sidebar ------------------------------------------------------
        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(248)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(16, 18, 16, 16)
        sl.setSpacing(6)

        brand = QLabel("J5 Harness")
        brand.setObjectName("brand")
        brand_sub = QLabel("multi-agent command center")
        brand_sub.setObjectName("brandSub")
        sl.addWidget(brand)
        sl.addWidget(brand_sub)
        sl.addSpacing(12)

        new_btn = QPushButton("+  New task")
        new_btn.setObjectName("ctaBtn")
        new_btn.setCursor(Qt.PointingHandCursor)
        new_btn.clicked.connect(lambda: (self._go("command"), self.command_view.prompt.setFocus()))
        sl.addWidget(new_btn)
        sl.addSpacing(10)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_btns: dict[str, QPushButton] = {}
        for i, (key, label, tip) in enumerate(NAV):
            btn = QPushButton(label)
            btn.setObjectName("navBtn")
            btn.setCheckable(True)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(tip)
            btn.clicked.connect(lambda _c, k=key: self._go(k))
            self.nav_group.addButton(btn, i)
            self.nav_btns[key] = btn
            sl.addWidget(btn)
        sl.addStretch(1)

        self.conn_dot = QLabel("●  Connected")
        self.conn_dot.setObjectName("muted")
        self.ver_lbl = QLabel(f"v{APP_VERSION}")
        self.ver_lbl.setObjectName("dim")
        sl.addWidget(self.conn_dot)
        sl.addWidget(self.ver_lbl)
        shell.addWidget(side)

        # -- right side: topbar + stack -----------------------------------
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        top = QWidget()
        top.setObjectName("topbar")
        top.setFixedHeight(54)
        tl = QHBoxLayout(top)
        tl.setContentsMargins(20, 0, 20, 0)
        self.view_title = QLabel("Command")
        self.view_title.setObjectName("viewTitle")
        self.project_combo = QComboBox()
        self.project_combo.setMinimumWidth(170)
        self.project_combo.currentTextChanged.connect(lambda _t: self.refresh_all(light=True))
        self.health_lbl = QLabel("")
        self.health_lbl.setObjectName("dim")
        pal_btn = QPushButton("⌘K")
        pal_btn.setObjectName("ghostBtn")
        pal_btn.setToolTip("Command palette (Ctrl+K)")
        pal_btn.clicked.connect(self._palette)
        tl.addWidget(self.view_title)
        tl.addStretch(1)
        tl.addWidget(self.health_lbl)
        tl.addWidget(QLabel("Project:"))
        tl.addWidget(self.project_combo)
        tl.addWidget(pal_btn)
        rl.addWidget(top)

        self.stack = QStackedWidget()
        self.command_view = CommandView(self.ctx)
        self.projects_view = TableView("Projects", "Enabled projects, domains and fallback ladders.",
                                       ["Name", "Domain", "Enabled", "Directory"])
        self.domains_view = TableView("Domains", "Model pools, skills, tools and data sources per domain.",
                                      ["Domain", "Primary models", "Skills", "Tools"])
        self.routing_view = RoutingView(self.ctx)
        self.delegation_view = DelegationView(self.ctx)
        self.kilo_view = KiloView(self.ctx)
        self.skills_view = SkillsView(self.ctx)
        self.bench_view = BenchView(self.ctx)
        self.config_view = ConfigView(self.ctx)
        self.logs_view = LogsView(self.ctx)
        self.views: dict[str, QWidget] = {
            "command": self.command_view,
            "projects": self.projects_view,
            "domains": self.domains_view,
            "routing": self.routing_view,
            "delegation": self.delegation_view,
            "kilo": self.kilo_view,
            "skills": self.skills_view,
            "bench": self.bench_view,
            "config": self.config_view,
            "logs": self.logs_view,
        }
        for key, _label, _tip in NAV:
            self.stack.addWidget(self.views[key])
        rl.addWidget(self.stack, 1)

        shell.addWidget(right, 1)

        # -- status bar ----------------------------------------------------
        status = QStatusBar()
        self.setStatusBar(status)
        self.status_project = QLabel("Project: -")
        self.status_flight = QLabel("In-flight: -")
        self.status_conn = QLabel("● Connected")
        self.ctx.project_combo = self.project_combo
        self.ctx.status_project = self.status_project
        self.ctx.status_flight = self.status_flight
        self.ctx.status_conn = self.status_conn
        status.addWidget(self.status_project)
        status.addWidget(self.status_flight)
        status.addPermanentWidget(self.status_conn)

        # table selection wiring
        self.projects_view.table.itemSelectionChanged.connect(self._project_selected)
        self.domains_view.table.itemSelectionChanged.connect(self._domain_selected)

        # shortcuts
        palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        palette_shortcut.activated.connect(self._palette)

        # auto-refresh timer (light)
        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh_all(light=True))
        self.timer.start(8000)

        self._go("command")
        self.refresh_all()

    # -- navigation ------------------------------------------------------
    def _go(self, key: str) -> None:
        self.stack.setCurrentWidget(self.views[key])
        self.nav_btns[key].setChecked(True)
        self.view_title.setText(dict((k, l) for k, l, _t in NAV)[key])
        if key == "skills":
            self.skills_view._load()
        if key == "logs":
            self.logs_view.refresh()

    def _palette(self) -> None:
        actions = [(g, l) for _k, l, g in [(k, l, t) for k, l, t in NAV]]
        actions += [("Actions", "New task"), ("Actions", "Run Kilo watcher once"),
                    ("Actions", "Refresh backend"), ("Actions", "Quit")]
        dlg = Palette(actions, self)
        if dlg.exec() and dlg.chosen:
            group, label = dlg.chosen
            if group == "Actions":
                if label == "New task":
                    self._go("command")
                    self.command_view.prompt.setFocus()
                elif label == "Run Kilo watcher once":
                    self._go("kilo")
                    self.kilo_view._watch()
                elif label == "Refresh backend":
                    self.refresh_all()
                elif label == "Quit":
                    self.close()
            else:
                for key, lbl, _tip in NAV:
                    if lbl == label:
                        self._go(key)
                        break

    # -- data ------------------------------------------------------------
    def refresh_all(self, light: bool = False) -> None:
        run_job(self.pool, self.backend.overview, self._apply_overview,
                lambda e: self._backend_down(e), )

    def _backend_down(self, err: str) -> None:
        self.status_conn.setText("● Backend degraded")
        self.status_conn.setStyleSheet(f"color: {C_ERROR};")
        self.conn_dot.setText("●  Backend degraded")
        self.command_view.add_feed(f"Backend degraded: {err[:160]}")

    def _apply_overview(self, res: BackendResult) -> None:
        if not res.ok:
            self._backend_down(res.error)
            return
        ov = res.payload
        # project combo (preserve selection)
        cur = self.project_combo.currentText()
        names = ov.get("projects", []) or []
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItems(names)
        if cur in names:
            self.project_combo.setCurrentText(cur)
        elif names:
            self.project_combo.setCurrentIndex(0)
        self.project_combo.blockSignals(False)

        status = ov.get("status", {}) or {}
        projects = status.get("projects", {}) or {}
        health = status.get("shared_health", {}) or {}
        scores = status.get("shared_scores", {}) or {}

        self.command_view.refresh_metrics(ov)

        # projects table
        rows = []
        for name in names:
            det = self.backend.project_detail(name)
            if det.ok:
                d = det.payload
                rows.append([d["name"], d["domain"], "yes" if d["enabled"] else "no", d["directory"]])
            else:
                rows.append([name, "-", "-", "-"])
        self.projects_view.set_rows(rows)

        # domains table
        drows = []
        for dname in ov.get("domains", []) or []:
            det = self.backend.domain_detail(dname)
            if det.ok:
                d = det.payload
                drows.append([d["name"], ", ".join(d["primary"][:2]),
                              str(len(d["skills"])), str(len(d["tools"]))])
            else:
                drows.append([dname, "-", "-", "-"])
        self.domains_view.set_rows(drows)

        # topbar health dots: first 5 models, green = not quarantined
        dots, up_count = [], 0
        for mid in list(health.keys())[:5]:
            q = (health[mid] or {}).get("quarantined", False)
            dots.append(f"<font color='{C_SUCCESS if not q else C_ERROR}'>●</font>")
            up_count += 0 if q else 1
        self.health_lbl.setText(f"{''.join(dots)}&nbsp;&nbsp;{up_count}/{len(dots)} models up" if dots else "no health data")

        proj = self.ctx.current_project()
        inflight = (projects.get(proj, {}) or {}).get("in_flight", "-")
        self.status_project.setText(f"Project: {proj}")
        self.status_flight.setText(f"In-flight: {inflight}")
        if self.backend.connected:
            self.status_conn.setText("● Connected")
            self.status_conn.setStyleSheet(f"color: {C_SUCCESS};")
            self.conn_dot.setText("●  Connected")

    def _project_selected(self) -> None:
        items = self.projects_view.table.selectedItems()
        if not items:
            return
        name = items[0].text()
        res = self.backend.project_detail(name)
        if not res.ok:
            self.projects_view.set_detail(f"Failed to load {name}:\n{res.error}")
            return
        d = res.payload
        lines = [f"{d['name']}  ({'enabled' if d['enabled'] else 'disabled'})",
                 f"Domain: {d['domain']}", f"Dir: {d['directory']}", "", "Fallback ladders:"]
        for role, ladder in d["ladders"].items():
            lines.append(f"  {role}: {' → '.join(ladder)}")
        lines += ["", f"Skills ({len(d['skills'])}): " + ", ".join(d["skills"][:12]),
                  f"Tools ({len(d['tools'])}): " + ", ".join(d["tools"][:12])]
        self.projects_view.set_detail("\n".join(lines))

    def _domain_selected(self) -> None:
        items = self.domains_view.table.selectedItems()
        if not items:
            return
        name = items[0].text()
        res = self.backend.domain_detail(name)
        if not res.ok:
            self.domains_view.set_detail(f"Failed to load {name}:\n{res.error}")
            return
        d = res.payload
        self.domains_view.set_detail(
            f"{d['name']}\n{d['description']}\n\nPrimary: {', '.join(d['primary'])}\n"
            f"Fallback: {', '.join(d['fallback'])}\n\nSkills ({len(d['skills'])}):\n  "
            + "\n  ".join(d["skills"][:20])
            + f"\n\nTools ({len(d['tools'])}):\n  " + "\n  ".join(d["tools"][:20])
        )

    def _on_delegated(self, res: BackendResult, prompt: str, task_id: str) -> None:
        self.command_view.send_btn.setEnabled(True)
        if not res.ok:
            self.command_view.add_feed(f"{task_id} failed: {res.error.splitlines()[0][:140]}")
            return
        d = res.payload
        _usage = d.get("usage") or {}
        _sess = d.get("session_id") or "-"
        self.command_view.add_feed(
            f"{task_id} → {d['state']} via {d['model_id']} (conf {d['confidence']:.2f}, "
            f"tokens {_usage.get('tokens_total', '-')}, session {_sess})"
        )
        self.logs_view.refresh()


# ---------------------------------------------------------------------------
# Dark titlebar (Windows) + entry point
# ---------------------------------------------------------------------------


def enable_dark_titlebar(window: MainWindow) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        value = ctypes.c_int(1)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attr, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                return
    except (AttributeError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    smoke = "--smoke" in argv
    if smoke:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Qt5 needs explicit high-DPI opt-in (Qt6 does this by default).
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("J5 Harness")
    app.setOrganizationName("J5")
    app.setStyleSheet(QSS)
    font = QFont("Inter", 10)
    font.setStyleHint(QFont.SansSerif)
    app.setFont(font)

    backend = Backend()
    win = MainWindow(backend)
    win.show()
    enable_dark_titlebar(win)

    if smoke:
        # Let the event loop pump once (timers, deferred layout), then quit.
        QTimer.singleShot(1500, app.quit)
        app.exec_()
        print("SMOKE_OK: window built, views=10, backend_connected="
              f"{backend.connected} boot_error={backend.boot_error!r}")
        return 0

    return int(app.exec_())


if __name__ == "__main__":
    sys.exit(main())
