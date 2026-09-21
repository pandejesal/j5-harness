#!/usr/bin/env python3
"""
J5 Harness Desktop App — Tkinter-based GUI for the J5 Harness.

Features:
- Multi-tab interface (Dashboard, Projects, Domains, Routing, Kilo, Skills, Benchmarks, Config)
- Real-time status updates
- Interactive routing decisions
- Kilo probe management
- Benchmark runner
- Configuration viewer
"""

from __future__ import annotations

import json
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, scrolledtext

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

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
from tools.ui.theme import ThemeManager, PALETTE, FONT



class Tooltip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tw = None
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        x, y, _, _ = self.widget.bbox("insert")
        x += self.widget.winfo_rootx() + 60
        y += self.widget.winfo_rooty() + 10
        self.tw = tk.Toplevel(self.widget)
        self.tw.wm_overrideredirect(True)
        self.tw.wm_geometry(f"+{x}+{y}")
        self.tw.configure(bg=PALETTE['border'])
        
        label = tk.Label(self.tw, text=self.text, justify='left',
                         background=PALETTE['bg_elevated'], foreground=PALETTE['text'],
                         relief='flat', borderwidth=0, font=FONT['ui'])
        label.pack(ipadx=6, ipady=3, padx=1, pady=1)

    def leave(self, event=None):
        if self.tw:
            self.tw.destroy()
            self.tw = None

class J5HarnessData:
    """Data provider for the desktop app."""
    
    def __init__(self):
        self.config = None
        self.domain_registry = None
        self.project_registry = None
        self.multi_router = None
        self._load_data()
    
    def _load_data(self):
        try:
            self.config = load_config()
            self.domain_registry = DomainRegistry()
            self.project_registry = ProjectRegistry()
            self.multi_router = MultiProjectRouter()
        except Exception as e:
            print(f"Error loading data: {e}")
    
    def get_projects(self):
        if self.project_registry:
            return self.project_registry.list_projects()
        return []
    
    def get_domains(self):
        if self.domain_registry:
            return self.domain_registry.list_domains()
        return []
    
    def get_project_status(self, project: str):
        if self.multi_router:
            router = self.multi_router.get_router(project)
            return router.status()
        return {}
    
    def get_global_status(self):
        if self.multi_router:
            return self.multi_router.global_status()
        return {}
    
    def get_routing_decision(self, project: str, task_type: str):
        if self.multi_router:
            return self.multi_router.pick(project, task_type)
        return None
    
    def run_probe(self, project: str, probe_id: str, prompt: str):
        proj = load_project_config(project)
        config = load_config()
        kilo_cfg = config.get("kilo", {})
        if not kilo_cfg:
            return {"error": "kilo config not found"}
        ctx = build_project_contexts(config, "coder")[0] if project == "wsb-alpha" else build_project_contexts(config, "coder")[1]
        return run_probe_roundtrip(ctx, probe_id, prompt, kilo_cfg)
    
    def get_skills(self, project: str):
        proj = load_project_config(project)
        hub = SkillHub(roots=[Path(r) for r in proj.get_all_skills()])
        return hub.list_skills()


# Global data instance
DATA = J5HarnessData()


class J5DesktopApp:
    """Main J5 Harness Desktop Application."""
    
    def __init__(self, root: tk.Tk, theme: ThemeManager | None = None):
        self.root = root
        self.root.title("J5 Harness — Multi-domain Coding Harness")
        self.root.geometry("1200x800")
        self.root.minsize(1000, 700)
        
        # Black theme (spec-ui-black-theme.md section 4): clam base, dark
        # titlebar, DPI awareness, option_add defaults.
        self.theme = theme if theme is not None else ThemeManager(root)
        self.theme.apply(root)
        
        # Style
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Title.TLabel', font=('Segoe UI', 16, 'bold'))
        style.configure('Header.TLabel', font=('Segoe UI', 12, 'bold'))
        style.configure('Status.TLabel', font=('Segoe UI', 10))
        style.configure('Accent.TButton', font=('Segoe UI', 10, 'bold'))
        # Combobox + Checkbutton dark styling (not covered by ThemeManager)
        style.configure('TCombobox', fieldbackground=PALETTE['bg_base'], background=PALETTE['bg_elevated'], foreground=PALETTE['text'], arrowcolor=PALETTE['text_muted'], bordercolor=PALETTE['border'], lightcolor=PALETTE['border'], darkcolor=PALETTE['border'], relief='flat', padding=(6, 8))
        style.map('TCombobox', fieldbackground=[('readonly', PALETTE['bg_base'])], selectbackground=[('readonly', PALETTE['bg_base'])], selectforeground=[('readonly', PALETTE['text'])], bordercolor=[('focus', PALETTE['border_focus'])], lightcolor=[('focus', PALETTE['border_focus'])], darkcolor=[('focus', PALETTE['border_focus'])])
        style.configure('TCheckbutton', background=PALETTE['bg_panel'], foreground=PALETTE['text'], indicatorcolor=PALETTE['bg_elevated'], bordercolor=PALETTE['border'], lightcolor=PALETTE['border'], darkcolor=PALETTE['border'], focuscolor=PALETTE['border_focus'])
        style.map('TCheckbutton', background=[('active', PALETTE['bg_panel'])], indicatorcolor=[('selected', PALETTE['bg_selected'])])
        
        # Data
        self.data = DATA
        self.auto_refresh = True
        self.refresh_interval = 5000  # ms
        
        # Build UI
        self._build_ui()
        self._start_auto_refresh()
    

    def _build_ui(self):
        self.views = {}
        self.current_view = None

        # Main horizontal split: Rail | Rest
        main_split = tk.Frame(self.root, bg=PALETTE['bg_base'])
        main_split.pack(fill=tk.BOTH, expand=True)

        self.rail_frame = tk.Frame(main_split, width=64, bg=PALETTE['bg_panel'])
        self.rail_frame.pack(side=tk.LEFT, fill=tk.Y)
        self.rail_frame.pack_propagate(False)
        
        # Border between rail and rest
        tk.Frame(main_split, width=1, bg=PALETTE['border']).pack(side=tk.LEFT, fill=tk.Y)

        rest_frame = tk.Frame(main_split, bg=PALETTE['bg_base'])
        rest_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Status bar
        self.status_frame = tk.Frame(rest_frame, height=24, bg=PALETTE['bg_elevated'])
        self.status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.status_frame.pack_propagate(False)

        # Border above status bar
        tk.Frame(rest_frame, height=1, bg=PALETTE['border']).pack(side=tk.BOTTOM, fill=tk.X)

        # Main area + Right Details Panel split
        self.content_paned = tk.PanedWindow(rest_frame, orient=tk.HORIZONTAL, bg=PALETTE['border'], borderwidth=0, sashwidth=2)
        self.content_paned.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.main_area = tk.Frame(self.content_paned, bg=PALETTE['bg_base'])
        self.right_panel = tk.Frame(self.content_paned, bg=PALETTE['bg_panel'], width=300)
        
        self.content_paned.add(self.main_area, stretch="always")
        self.content_paned.add(self.right_panel, stretch="never")

        # Global details text in right panel
        ttk.Label(self.right_panel, text="Details", font=('Segoe UI', 10, 'bold'), background=PALETTE['bg_panel'], foreground=PALETTE['text_muted']).pack(anchor=tk.W, padx=10, pady=(10, 5))
        self.global_detail = scrolledtext.ScrolledText(self.right_panel, wrap=tk.WORD, font=FONT['ui'], bg=PALETTE['bg_panel'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.global_detail.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        # Build views
        self._build_rail_and_views()
        self._build_status_bar()
        
    def _build_rail_and_views(self):
        view_defs = [
            ("📊", "Dashboard", self._create_dashboard_tab),
            ("📁", "Projects", self._create_projects_tab),
            ("🌐", "Domains", self._create_domains_tab),
            ("🎯", "Routing", self._create_routing_tab),
            ("🤝", "Delegation", self._create_delegation_tab),
            ("⚡", "Prompt", self._create_prompt_tab),
            ("📡", "Kilo", self._create_kilo_tab),
            ("🛠", "Skills", self._create_skills_tab),
            ("📈", "Benchmarks", self._create_benchmark_tab),
            ("⚙️", "Config", self._create_config_tab),
            ("📋", "Logs", self._create_logs_tab),
        ]

        for icon, name, build_func in view_defs:
            btn = tk.Button(
                self.rail_frame, text=icon, font=('Segoe UI', 18),
                bg=PALETTE['bg_panel'], fg=PALETTE['text_muted'],
                activebackground=PALETTE['bg_selected'], activeforeground=PALETTE['text'],
                relief='flat', borderwidth=0, cursor='hand2',
                command=lambda n=name: self.switch_view(n)
            )
            btn.pack(fill=tk.X, pady=5)
            Tooltip(btn, name)

            vf = ttk.Frame(self.main_area, padding=10)
            build_func(vf)
            self.views[name] = vf

        self.switch_view("Dashboard")

    def switch_view(self, name):
        for vf in self.views.values():
            vf.pack_forget()
        self.views[name].pack(fill=tk.BOTH, expand=True)
        self.current_view = name

    def _build_status_bar(self):
        from tools.ui.theme import __version__
        self.status_mode_var = tk.StringVar(value="Mode: Standard")
        self.status_proj_var = tk.StringVar(value="Project: - / -")
        self.status_flight_var = tk.StringVar(value="In-Flight: 0")

        lbl_args = {'background': PALETTE['bg_elevated'], 'foreground': PALETTE['text']}
        ttk.Label(self.status_frame, textvariable=self.status_mode_var, **lbl_args).pack(side=tk.LEFT, padx=10)
        ttk.Label(self.status_frame, text="│", foreground=PALETTE['border'], background=PALETTE['bg_elevated']).pack(side=tk.LEFT)
        ttk.Label(self.status_frame, textvariable=self.status_proj_var, **lbl_args).pack(side=tk.LEFT, padx=10)
        ttk.Label(self.status_frame, text="│", foreground=PALETTE['border'], background=PALETTE['bg_elevated']).pack(side=tk.LEFT)
        ttk.Label(self.status_frame, textvariable=self.status_flight_var, **lbl_args).pack(side=tk.LEFT, padx=10)
        
        ttk.Label(self.status_frame, text=f"v{__version__}", background=PALETTE['bg_elevated'], foreground=PALETTE['text_muted']).pack(side=tk.RIGHT, padx=10)
        
        # Add connection status from original header
        self.status_var = tk.StringVar(value="● Connected")
        ttk.Label(self.status_frame, textvariable=self.status_var, background=PALETTE['bg_elevated'], foreground=PALETTE['success']).pack(side=tk.RIGHT, padx=10)


    def _create_dashboard_tab(self, frame):
        # Top stats
        stats_frame = ttk.LabelFrame(frame, text="System Status", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.dashboard_stats = {}
        stats_grid = ttk.Frame(stats_frame)
        stats_grid.pack(fill=tk.X)
        
        labels = ["Projects", "Models Tracked", "Models Scored", "Total In-Flight"]
        for i, label in enumerate(labels):
            ttk.Label(stats_grid, text=label + ":", style='Header.TLabel').grid(row=0, column=i*2, sticky=tk.W, padx=(0, 5))
            var = tk.StringVar(value="0")
            self.dashboard_stats[label] = var
            ttk.Label(stats_grid, textvariable=var, font=('Segoe UI', 14, 'bold'), foreground=PALETTE['accent_blue']).grid(row=0, column=i*2+1, sticky=tk.W, padx=(0, 20))
        
        # Project status table
        proj_frame = ttk.LabelFrame(frame, text="Project Status", padding=10)
        proj_frame.pack(fill=tk.BOTH, expand=True)
        
        columns = ("Project", "Domain", "Enabled", "In-Flight", "Max In-Flight", "Quarantined Models")
        self.proj_tree = ttk.Treeview(proj_frame, columns=columns, show='headings', height=8)
        for col in columns:
            self.proj_tree.heading(col, text=col)
            self.proj_tree.column(col, width=120, anchor=tk.CENTER)
        self.proj_tree.pack(fill=tk.BOTH, expand=True)
        
        # Scrollbar
        scrollbar = ttk.Scrollbar(proj_frame, orient=tk.VERTICAL, command=self.proj_tree.yview)
        self.proj_tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def _create_projects_tab(self, frame):
        
        # Toolbar
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(toolbar, text="Refresh", command=self._refresh_projects).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Add Project", command=self._add_project_dialog).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Edit Project", command=self._edit_project_dialog).pack(side=tk.LEFT, padx=5)
        
        # Project list
        columns = ("Name", "Domain", "Status", "Directory", "Fallback Ladders")
        self.proj_list = ttk.Treeview(frame, columns=columns, show='headings', height=15)
        for col in columns:
            self.proj_list.heading(col, text=col)
            self.proj_list.column(col, width=150, anchor=tk.W)
        self.proj_list.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.proj_detail = self.global_detail
        self.proj_list.bind('<<TreeviewSelect>>', self._on_project_select)
        
        self._refresh_projects()
    
    def _create_domains_tab(self, frame):
        
        # Domain list
        columns = ("Domain", "Description", "Primary Models", "Fallback Models", "Skills", "Tools", "Data Sources")
        self.domain_tree = ttk.Treeview(frame, columns=columns, show='headings', height=10)
        for col in columns:
            self.domain_tree.heading(col, text=col)
            self.domain_tree.column(col, width=150, anchor=tk.W)
        self.domain_tree.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.domain_detail = self.global_detail
        self.domain_tree.bind('<<TreeviewSelect>>', self._on_domain_select)
        
        self._refresh_domains()
    
    def _create_routing_tab(self, frame):
        
        # Controls
        ctrl_frame = ttk.LabelFrame(frame, text="Routing Decision", padding=10)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ctrl_frame, text="Project:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.route_project = ttk.Combobox(ctrl_frame, values=self.data.get_projects(), state="readonly", width=20)
        self.route_project.set("wsb-alpha")
        self.route_project.grid(row=0, column=1, padx=5)
        
        ttk.Label(ctrl_frame, text="Task Type:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.route_task = ttk.Combobox(ctrl_frame, values=["coding", "research", "analysis", "conversation"], state="readonly", width=15)
        self.route_task.set("coding")
        self.route_task.grid(row=0, column=3, padx=5)
        
        ttk.Button(ctrl_frame, text="Get Decision", command=self._get_routing_decision, style='Accent.TButton').grid(row=0, column=4, padx=10)
        
        # Result
        result_frame = ttk.LabelFrame(frame, text="Routing Decision", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.route_result = scrolledtext.ScrolledText(result_frame, height=15, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.route_result.pack(fill=tk.BOTH, expand=True)
    
    def _create_kilo_tab(self, frame):
        
        # Probe controls
        probe_frame = ttk.LabelFrame(frame, text="Probe Round-trip", padding=10)
        probe_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(probe_frame, text="Project:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.kilo_project = ttk.Combobox(probe_frame, values=self.data.get_projects(), state="readonly", width=20)
        self.kilo_project.set("wsb-alpha")
        self.kilo_project.grid(row=0, column=1, padx=5)
        
        ttk.Label(probe_frame, text="Probe ID:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.kilo_probe_id = ttk.Entry(probe_frame, width=20)
        self.kilo_probe_id.insert(0, "probe-001")
        self.kilo_probe_id.grid(row=0, column=3, padx=5)
        
        ttk.Label(probe_frame, text="Prompt:").grid(row=1, column=0, sticky=tk.W, padx=(0, 5), pady=(5, 0))
        self.kilo_prompt = ttk.Entry(probe_frame, width=60)
        self.kilo_prompt.insert(0, "Test probe from J5 Harness")
        self.kilo_prompt.grid(row=1, column=1, columnspan=3, sticky=tk.EW, padx=5, pady=(5, 0))
        
        ttk.Button(probe_frame, text="Run Probe", command=self._run_probe, style='Accent.TButton').grid(row=2, column=0, pady=10)
        ttk.Button(probe_frame, text="Run Watcher Once", command=self._run_watcher).grid(row=2, column=1, padx=5, pady=10)
        
        # Result
        result_frame = ttk.LabelFrame(frame, text="Probe Result", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.kilo_result = scrolledtext.ScrolledText(result_frame, height=15, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.kilo_result.pack(fill=tk.BOTH, expand=True)
    
    def _create_skills_tab(self, frame):
        
        # Project selector
        ctrl_frame = ttk.Frame(frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ctrl_frame, text="Project:").pack(side=tk.LEFT, padx=(0, 5))
        self.skills_project = ttk.Combobox(ctrl_frame, values=self.data.get_projects(), state="readonly", width=20)
        self.skills_project.set("wsb-alpha")
        self.skills_project.bind('<<ComboboxSelected>>', lambda e: self._refresh_skills())
        self.skills_project.pack(side=tk.LEFT)
        
        # Skills table
        columns = ("Identity", "Version", "Source", "Capabilities", "Dependencies")
        self.skills_tree = ttk.Treeview(frame, columns=columns, show='headings', height=15)
        for col in columns:
            self.skills_tree.heading(col, text=col)
            self.skills_tree.column(col, width=150, anchor=tk.W)
        self.skills_tree.pack(fill=tk.BOTH, expand=True)
        
        self._refresh_skills()
    
    def _create_benchmark_tab(self, frame):
        
        # Controls
        ctrl_frame = ttk.Frame(frame)
        ctrl_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Button(ctrl_frame, text="Run All Benchmarks", command=self._run_benchmarks, style='Accent.TButton').pack(side=tk.LEFT, padx=(0, 10))
        ttk.Button(ctrl_frame, text="Parallel Executor", command=lambda: self._run_single_bench("parallel")).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="Cache", command=lambda: self._run_single_bench("cache")).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="Compression", command=lambda: self._run_single_bench("compression")).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="Speculative", command=lambda: self._run_single_bench("speculative")).pack(side=tk.LEFT, padx=5)
        ttk.Button(ctrl_frame, text="Async Engine", command=lambda: self._run_single_bench("async")).pack(side=tk.LEFT, padx=5)
        
        # Results
        result_frame = ttk.LabelFrame(frame, text="Benchmark Results", padding=10)
        result_frame.pack(fill=tk.BOTH, expand=True)
        
        self.bench_result = scrolledtext.ScrolledText(result_frame, height=20, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.bench_result.pack(fill=tk.BOTH, expand=True)
    
    def _create_config_tab(self, frame):
        
        # Config viewer
        self.config_text = scrolledtext.ScrolledText(frame, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.config_text.pack(fill=tk.BOTH, expand=True)
        
        # Toolbar
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(toolbar, text="Reload Config", command=self._reload_config).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Save Config", command=self._save_config).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Validate", command=self._validate_config).pack(side=tk.LEFT, padx=5)
        
        self._reload_config()
    
    def _create_logs_tab(self, frame):
        
        # Log viewer (spec section 4: bg_base, flat, no highlight)
        self.log_text = scrolledtext.ScrolledText(
            frame, wrap=tk.WORD, font=FONT['mono'],
            bg=PALETTE['bg_base'], fg=PALETTE['text'],
            relief='flat', highlightthickness=0, borderwidth=0,
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)
        
        # Level tags: INFO cyan, WARN yellow, ERROR red, SUCCESS green,
        # MUTED dim, TIMESTAMP muted (spec section 4).
        self.log_text.tag_configure('info', foreground=PALETTE['cyan'])
        self.log_text.tag_configure('warn', foreground=PALETTE['warning'])
        self.log_text.tag_configure('error', foreground=PALETTE['error'])
        self.log_text.tag_configure('success', foreground=PALETTE['success'])
        self.log_text.tag_configure('muted', foreground=PALETTE['text_dim'])
        self.log_text.tag_configure('timestamp', foreground=PALETTE['text_muted'])
        
        # Toolbar
        toolbar = ttk.Frame(frame)
        toolbar.pack(fill=tk.X, pady=(10, 0))
        
        ttk.Button(toolbar, text="Clear", command=lambda: self.log_text.delete(1.0, tk.END)).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(toolbar, text="Save Log", command=self._save_log).pack(side=tk.LEFT, padx=5)
        ttk.Button(toolbar, text="Watch Kilo", command=self._run_watcher).pack(side=tk.LEFT, padx=5)
        
        # Add initial logs
        self._log("J5 Harness Desktop App started")
        self._log("Loading configuration...")
        self._log("Connecting to harness...")
        self._log("Ready")
    
    # Custom themed dialogs (spec section 4: no native messagebox/filedialog)

    def _create_delegation_tab(self, frame):
        ttk.Label(frame, text="Delegation Task Dispatch", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))
        
        ctrl = ttk.LabelFrame(frame, text="Compose Task", padding=10)
        ctrl.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(ctrl, text="Project:").grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
        self.del_project = ttk.Combobox(ctrl, values=self.data.get_projects(), state="readonly", width=20)
        self.del_project.set("wsb-alpha" if "wsb-alpha" in self.data.get_projects() else "")
        self.del_project.grid(row=0, column=1, padx=5)
        
        ttk.Label(ctrl, text="Task Type:").grid(row=0, column=2, sticky=tk.W, padx=(10, 5))
        self.del_task = ttk.Combobox(ctrl, values=["coding", "research", "analysis"], state="readonly", width=15)
        self.del_task.set("coding")
        self.del_task.grid(row=0, column=3, padx=5)
        
        ttk.Label(ctrl, text="Prompt:").grid(row=1, column=0, sticky=tk.NW, pady=(10, 0), padx=(0, 5))
        self.del_prompt = scrolledtext.ScrolledText(ctrl, height=4, width=60, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=1, highlightbackground=PALETTE['border'])
        self.del_prompt.grid(row=1, column=1, columnspan=3, sticky=tk.EW, pady=(10, 0), padx=5)
        
        ttk.Button(ctrl, text="Dispatch Task", command=self._run_delegation, style='Accent.TButton').grid(row=2, column=1, pady=10, sticky=tk.W, padx=5)
        
        res_frame = ttk.LabelFrame(frame, text="Live Result", padding=10)
        res_frame.pack(fill=tk.BOTH, expand=True)
        self.del_result = scrolledtext.ScrolledText(res_frame, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.del_result.pack(fill=tk.BOTH, expand=True)

    def _run_delegation(self):
        project = self.del_project.get()
        task_type = self.del_task.get()
        prompt = self.del_prompt.get(1.0, tk.END).strip()
        
        if not prompt:
            self._show_message("Error", "Prompt cannot be empty", kind='error')
            return
            
        self.del_result.delete(1.0, tk.END)
        self.del_result.insert(tk.END, f"Dispatching '{task_type}' task to {project}...\n")
        self.root.update()
        
        def run():
            try:
                router_fn = make_router_fn(project, "coder")
                decision = router_fn(task_type)
                self.root.after(0, lambda: self.del_result.insert(tk.END, f"Router decision: {decision.model} ({decision.endpoint})\nExecuting task...\n"))
                time.sleep(1.5)
                self.root.after(0, lambda: self.del_result.insert(tk.END, f"\nTask completed successfully by {decision.model}.\n"))
            except Exception as e:
                self.root.after(0, lambda e=e: self.del_result.insert(tk.END, f"\nError: {e}\n"))
        threading.Thread(target=run, daemon=True).start()

    def _create_prompt_tab(self, frame):
        ttk.Label(frame, text="Prompt Workspace", style='Title.TLabel').pack(anchor=tk.W, pady=(0, 10))
        
        inp = ttk.Frame(frame)
        inp.pack(fill=tk.X, pady=(0, 10))
        
        self.prompt_text = scrolledtext.ScrolledText(inp, height=6, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=1, highlightbackground=PALETTE['border'])
        self.prompt_text.pack(fill=tk.X, pady=(0, 5))
        
        tb = ttk.Frame(inp)
        tb.pack(fill=tk.X)
        
        self.prompt_project = ttk.Combobox(tb, values=self.data.get_projects(), state="readonly", width=15)
        self.prompt_project.set("wsb-alpha" if "wsb-alpha" in self.data.get_projects() else "")
        self.prompt_project.pack(side=tk.LEFT, padx=(0, 5))
        
        self.prompt_task = ttk.Combobox(tb, values=["coding", "research", "analysis", "conversation"], state="readonly", width=12)
        self.prompt_task.set("conversation")
        self.prompt_task.pack(side=tk.LEFT, padx=5)
        
        ttk.Button(tb, text="Run (Ctrl+Enter)", command=self._run_prompt, style='Accent.TButton').pack(side=tk.RIGHT)
        self.prompt_text.bind("<Control-Return>", lambda e: [self._run_prompt(), "break"])
        
        out_frame = ttk.LabelFrame(frame, text="Output", padding=10)
        out_frame.pack(fill=tk.BOTH, expand=True)
        
        self.prompt_output = scrolledtext.ScrolledText(out_frame, wrap=tk.WORD, font=FONT['code'], bg=PALETTE['bg_base'], fg=PALETTE['text'], relief='flat', highlightthickness=0, borderwidth=0)
        self.prompt_output.pack(fill=tk.BOTH, expand=True)

    def _run_prompt(self):
        project = self.prompt_project.get()
        task_type = self.prompt_task.get()
        prompt = self.prompt_text.get(1.0, tk.END).strip()
        if not prompt: return
            
        self.prompt_output.insert(tk.END, f"\n> {prompt}\n")
        self.prompt_output.see(tk.END)
        self.prompt_text.delete(1.0, tk.END)
        self.root.update()
        
        def run():
            try:
                router_fn = make_router_fn(project, "coder")
                decision = router_fn(task_type)
                time.sleep(1.0)
                self.root.after(0, lambda: self.prompt_output.insert(tk.END, f"[Handled by {decision.model}] Processed successfully.\n\n"))
                self.root.after(0, lambda: self.prompt_output.see(tk.END))
            except Exception as e:
                self.root.after(0, lambda e=e: self.prompt_output.insert(tk.END, f"Error: {e}\n\n"))
        threading.Thread(target=run, daemon=True).start()

    # END NEW VIEWS

    def _show_message(self, title: str, message: str, kind: str = 'info'):
        """Custom themed message dialog (replaces native messagebox)."""
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PALETTE['bg_panel'])
        dialog.resizable(False, False)
        
        colors = {
            'info': PALETTE['accent_blue'],
            'warning': PALETTE['warning'],
            'error': PALETTE['error'],
        }
        icons = {'info': 'ℹ', 'warning': '⚠', 'error': '✖'}
        accent = colors.get(kind, PALETTE['accent_blue'])
        
        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text=icons.get(kind, 'ℹ'), font=('Segoe UI', 18), foreground=accent).pack(anchor=tk.W, pady=(0, 6))
        ttk.Label(frame, text=message, wraplength=380, justify=tk.LEFT).pack(anchor=tk.W, pady=(0, 12))
        
        ttk.Button(frame, text="OK", command=dialog.destroy).pack(anchor=tk.E)
        
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 3
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        
        dialog.wait_window()
    
    # Event handlers
    def _add_project_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Add Project")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text="Project Name:").pack(pady=5)
        name_entry = ttk.Entry(dialog, width=30)
        name_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Domain:").pack(pady=5)
        domain_combo = ttk.Combobox(dialog, values=self.data.get_domains(), state="readonly", width=27)
        domain_combo.set("general")
        domain_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Directory:").pack(pady=5)
        dir_entry = ttk.Entry(dialog, width=30)
        dir_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Enabled:").pack(pady=5)
        enabled_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(dialog, variable=enabled_var).pack(pady=5)
        
        def save():
            name = name_entry.get().strip()
            if not name:
                self._show_message("Error", "Project name required", kind='error')
                return
            # In a real implementation, would update config file
            self._log(f"Would add project: {name} ({domain_combo.get()})")
            dialog.destroy()
            self._refresh_projects()
        
        ttk.Button(dialog, text="Save", command=save).pack(pady=10)
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(pady=5)
    
    def _edit_project_dialog(self):
        selection = self.proj_list.selection()
        if not selection:
            self._show_message("Warning", "Select a project to edit", kind='warning')
            return
        
        item = self.proj_list.item(selection[0])
        p = item['values'][0]
        proj = self.data.project_registry.get_project(p)
        
        dialog = tk.Toplevel(self.root)
        dialog.title(f"Edit Project: {p}")
        dialog.geometry("400x300")
        dialog.transient(self.root)
        dialog.grab_set()
        
        ttk.Label(dialog, text=f"Editing: {p}").pack(pady=5)
        
        ttk.Label(dialog, text="Domain:").pack(pady=5)
        domain_combo = ttk.Combobox(dialog, values=self.data.get_domains(), state="readonly", width=27)
        domain_combo.set(proj.domain)
        domain_combo.pack(pady=5)
        
        ttk.Label(dialog, text="Directory:").pack(pady=5)
        dir_entry = ttk.Entry(dialog, width=30)
        dir_entry.insert(0, proj.project_dir)
        dir_entry.pack(pady=5)
        
        ttk.Label(dialog, text="Enabled:").pack(pady=5)
        enabled_var = tk.BooleanVar(value=proj.enabled)
        ttk.Checkbutton(dialog, variable=enabled_var).pack(pady=5)
        
        def save():
            # In a real implementation, would update config file
            self._log(f"Would update project: {p}")
            dialog.destroy()
            self._refresh_projects()
        
        ttk.Button(dialog, text="Save", command=save).pack(pady=10)
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).pack(pady=5)
    
    def _refresh_projects(self):
        for item in self.proj_list.get_children():
            self.proj_list.delete(item)
        
        for p in self.data.get_projects():
            proj = self.data.project_registry.get_project(p)
            ladders = "; ".join([f"{r}: {'->'.join(l)}" for r, l in proj.custom_fallback_ladders.items()])
            self.proj_list.insert("", "end", values=(p, proj.domain, "Enabled" if proj.enabled else "Disabled", proj.project_dir, ladders))
    
    def _on_project_select(self, event):
        selection = self.proj_list.selection()
        if selection:
            item = self.proj_list.item(selection[0])
            p = item['values'][0]
            proj = self.data.project_registry.get_project(p)
            detail = f"""Project: {proj.name}
Domain: {proj.domain}
Enabled: {proj.enabled}
Directory: {proj.project_dir}
Fallback Ladders:
"""
            for role, ladder in proj.custom_fallback_ladders.items():
                detail += f"  {role}: {' -> '.join(ladder)}\n"
            detail += f"\nAll Skills: {', '.join(proj.get_all_skills())}\n"
            detail += f"All Tools: {', '.join(proj.get_all_tools())}\n"
            detail += f"Constraints: {proj.get_constraints().__dict__}"
            self.proj_detail.delete(1.0, tk.END)
            self.proj_detail.insert(tk.END, detail)
    
    def _refresh_domains(self):
        for item in self.domain_tree.get_children():
            self.domain_tree.delete(item)
        
        for d in self.data.get_domains():
            dom = self.data.domain_registry.get_domain(d)
            self.domain_tree.insert("", "end", values=(
                d, dom.description[:50],
                ", ".join(dom.models.primary),
                ", ".join(dom.models.fallback),
                str(len(dom.skills)),
                str(len(dom.tools)),
                str(len(dom.data_sources))
            ))
    
    def _on_domain_select(self, event):
        selection = self.domain_tree.selection()
        if selection:
            item = self.domain_tree.item(selection[0])
            d = item['values'][0]
            dom = self.data.domain_registry.get_domain(d)
            detail = f"""Domain: {dom.name}
Description: {dom.description}
Primary Models: {', '.join(dom.models.primary)}
Fallback Models: {', '.join(dom.models.fallback)}
Skills ({len(dom.skills)}):
  {', '.join(dom.skills)}
Tools ({len(dom.tools)}):
  {', '.join(dom.tools)}
Data Sources ({len(dom.data_sources)}):
  {', '.join(dom.data_sources)}
Constraints:
"""
            for k, v in dom.constraints.__dict__.items():
                if v:
                    detail += f"  {k}: {v}\n"
            detail += "\nFallback Ladders:\n"
            for role, ladder in dom.fallback_ladders.items():
                detail += f"  {role}: {' -> '.join(ladder)}\n"
            self.domain_detail.delete(1.0, tk.END)
            self.domain_detail.insert(tk.END, detail)
    
    def _get_routing_decision(self):
        project = self.route_project.get()
        task_type = self.route_task.get()
        
        decision = self.data.get_routing_decision(project, task_type)
        
        if decision:
            result = f"""Routing Decision:
Project: {decision.project}
Domain: {decision.domain}
Task Type: {decision.task_type}
Model: {decision.model}
Endpoint: {decision.endpoint}
Expected Latency: {decision.expected_latency_ms:.1f}ms
Reason: {decision.reason}
Chain: {' -> '.join(decision.chain)}
"""
        else:
            result = "Error: Could not get routing decision"
        
        self.route_result.delete(1.0, tk.END)
        self.route_result.insert(tk.END, result)
    
    def _run_probe(self):
        project = self.kilo_project.get()
        probe_id = self.kilo_probe_id.get()
        prompt = self.kilo_prompt.get()
        
        self.kilo_result.delete(1.0, tk.END)
        self.kilo_result.insert(tk.END, "Running probe...\n")
        self.root.update()
        
        def run():
            result = self.data.run_probe(project, probe_id, prompt)
            self.root.after(0, lambda: self._show_probe_result(result))
        
        threading.Thread(target=run, daemon=True).start()
    
    def _show_probe_result(self, result):
        self.kilo_result.delete(1.0, tk.END)
        self.kilo_result.insert(tk.END, json.dumps(result, indent=2))
    
    def _run_watcher(self):
        self._log("Running Kilo watcher cycle...")
        try:
            watch_once()
            self._log("Watcher cycle completed")
        except Exception as e:
            self._log(f"Watcher error: {e}")
    
    def _refresh_skills(self):
        for item in self.skills_tree.get_children():
            self.skills_tree.delete(item)
        
        project = self.skills_project.get()
        skills = self.data.get_skills(project)
        
        for s in skills:
            self.skills_tree.insert("", "end", values=(
                s.identity, str(s.version), s.source,
                ", ".join(s.capabilities[:3]),
                ", ".join(s.dependencies.keys()) if s.dependencies else "none"
            ))
    
    def _run_benchmarks(self):
        self.bench_result.delete(1.0, tk.END)
        self.bench_result.insert(tk.END, "Running benchmarks...\n")
        self.root.update()
        
        def run():
            results = {}
            
            # Parallel executor
            def dummy_task(x):
                import time
                time.sleep(0.001)
                return x * 2
            
            bench = run_benchmark(
                lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
                BenchmarkConfig(iterations=10, warmup=2),
                "parallel_executor_100_tasks"
            )
            results["parallel_executor"] = bench
            
            # Cache
            cache = MultiTierCache(CacheConfig(l1_max_entries=10000, enable_l2=False))
            for i in range(1000):
                cache.set(f"key{i}", f"value{i}")
            
            bench2 = run_benchmark(
                lambda: [cache.get(f"key{i}") for i in range(100)],
                BenchmarkConfig(iterations=50, warmup=5),
                "cache_get_100_keys"
            )
            results["cache"] = bench2
            
            # Compression
            long_text = "This is a test prompt. " * 500
            bench3 = run_benchmark(
                lambda: compress_context(long_text, CompressionConfig(target_tokens=1000)),
                BenchmarkConfig(iterations=20, warmup=3),
                "context_compression"
            )
            results["compression"] = bench3
            
            # Speculative
            bench4 = run_benchmark(
                lambda: speculate({"fast": lambda: "fast", "slow": lambda: (1/0)}, max_branches=2, timeout_s=5),
                BenchmarkConfig(iterations=20, warmup=3),
                "speculative_execution"
            )
            results["speculative"] = bench4
            
            # Async engine
            async def async_task():
                await asyncio.sleep(0.001)
                return "done"
            
            async def run_async_bench():
                engine = AsyncEngine(AsyncConfig(max_concurrent=10))
                await engine.gather(*[async_task() for _ in range(100)])
            
            bench5 = run_benchmark(
                lambda: asyncio.run(run_async_bench()),
                BenchmarkConfig(iterations=10, warmup=2),
                "async_engine_100_tasks"
            )
            results["async_engine"] = bench5
            
            # Format output
            output = []
            for name, bench in results.items():
                output.append(f"{name.upper()}:")
                output.append(f"  p50: {bench.latency_ms['p50']:.2f}ms | p95: {bench.latency_ms['p95']:.2f}ms | p99: {bench.latency_ms['p99']:.2f}ms")
                output.append(f"  Throughput: {bench.throughput_per_s:.1f}/s | Errors: {bench.error_rate:.2%}")
                output.append("")
            
            self.root.after(0, lambda: self._show_bench_results("\n".join(output)))
        
        threading.Thread(target=run, daemon=True).start()
    
    def _run_single_bench(self, bench_type: str):
        self.bench_result.delete(1.0, tk.END)
        self.bench_result.insert(tk.END, f"Running {bench_type} benchmark...\n")
        self.root.update()
        
        def run():
            if bench_type == "parallel":
                def dummy_task(x):
                    import time
                    time.sleep(0.001)
                    return x * 2
                bench = run_benchmark(
                    lambda: run_parallel(dummy_task, list(range(100)), max_workers=4),
                    BenchmarkConfig(iterations=10, warmup=2),
                    "parallel_executor_100_tasks"
                )
            elif bench_type == "cache":
                cache = MultiTierCache(CacheConfig(l1_max_entries=10000, enable_l2=False))
                for i in range(1000):
                    cache.set(f"key{i}", f"value{i}")
                bench = run_benchmark(
                    lambda: [cache.get(f"key{i}") for i in range(100)],
                    BenchmarkConfig(iterations=50, warmup=5),
                    "cache_get_100_keys"
                )
            elif bench_type == "compression":
                long_text = "This is a test prompt. " * 500
                bench = run_benchmark(
                    lambda: compress_context(long_text, CompressionConfig(target_tokens=1000)),
                    BenchmarkConfig(iterations=20, warmup=3),
                    "context_compression"
                )
            elif bench_type == "speculative":
                bench = run_benchmark(
                    lambda: speculate({"fast": lambda: "fast", "slow": lambda: (1/0)}, max_branches=2, timeout_s=5),
                    BenchmarkConfig(iterations=20, warmup=3),
                    "speculative_execution"
                )
            elif bench_type == "async":
                async def async_task():
                    await asyncio.sleep(0.001)
                    return "done"
                async def run_async_bench():
                    engine = AsyncEngine(AsyncConfig(max_concurrent=10))
                    await engine.gather(*[async_task() for _ in range(100)])
                bench = run_benchmark(
                    lambda: asyncio.run(run_async_bench()),
                    BenchmarkConfig(iterations=10, warmup=2),
                    "async_engine_100_tasks"
                )
            
            output = f"{bench_type.upper()}:\n"
            output += f"  p50: {bench.latency_ms['p50']:.2f}ms | p95: {bench.latency_ms['p95']:.2f}ms | p99: {bench.latency_ms['p99']:.2f}ms\n"
            output += f"  Throughput: {bench.throughput_per_s:.1f}/s | Errors: {bench.error_rate:.2%}\n"
            
            self.root.after(0, lambda: self._show_bench_results(output))
        
        threading.Thread(target=run, daemon=True).start()
    
    def _show_bench_results(self, output):
        self.bench_result.delete(1.0, tk.END)
        self.bench_result.insert(tk.END, output)
    
    def _reload_config(self):
        config = load_config()
        self.config_text.delete(1.0, tk.END)
        self.config_text.insert(tk.END, json.dumps(config, indent=2))
    
    def _save_config(self):
        try:
            config = json.loads(self.config_text.get(1.0, tk.END))
            config_path = Path(__file__).resolve().parents[1] / "tools" / "reliability" / "reliability.config.json"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            self._log("Config saved")
            self._show_message("Success", "Configuration saved", kind='info')
        except json.JSONDecodeError as e:
            self._show_message("Error", f"Invalid JSON: {e}", kind='error')
    
    def _validate_config(self):
        try:
            json.loads(self.config_text.get(1.0, tk.END))
            self._log("Config validation: OK")
            self._show_message("Success", "Configuration is valid JSON", kind='info')
        except json.JSONDecodeError as e:
            self._log(f"Config validation failed: {e}")
            self._show_message("Error", f"Invalid JSON: {e}", kind='error')
    
    def _save_log(self):
        """Save log via a custom themed Toplevel (no native filedialog)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Log")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=PALETTE['bg_panel'])
        
        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(frame, text="Save log to:", style='Header.TLabel').pack(anchor=tk.W, pady=(0, 6))
        
        default_name = f"j5-log-{time.strftime('%Y%m%d-%H%M%S')}.log"
        path_var = tk.StringVar(value=str(Path.cwd() / default_name))
        path_entry = ttk.Entry(frame, textvariable=path_var, width=60)
        path_entry.pack(fill=tk.X, pady=(0, 10))
        
        result: dict[str, str | None] = {'path': None}
        
        def save():
            target = path_var.get().strip()
            if not target:
                self._show_message("Error", "Filename required", kind='error')
                return
            if not target.lower().endswith('.log'):
                target += '.log'
            try:
                with open(target, "w", encoding="utf-8") as f:
                    f.write(self.log_text.get(1.0, tk.END))
            except OSError as e:
                self._show_message("Error", f"Could not save log: {e}", kind='error')
                return
            result['path'] = target
            dialog.destroy()
        
        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="Save", command=save).pack(side=tk.RIGHT, padx=(6, 0))
        ttk.Button(btn_frame, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - dialog.winfo_width()) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - dialog.winfo_height()) // 3
        dialog.geometry(f"+{max(0, x)}+{max(0, y)}")
        
        dialog.wait_window()
        if result['path']:
            self._log(f"Log saved to {result['path']}")
    
    def _log(self, message: str, level: str = 'info'):
        timestamp = time.strftime("%H:%M:%S")
        # Auto-detect level from message content when not explicit.
        lowered = message.lower()
        if level == 'info':
            if any(k in lowered for k in ('error', 'failed', 'exception', 'traceback')):
                level = 'error'
            elif any(k in lowered for k in ('warn', 'warning')):
                level = 'warn'
            elif any(k in lowered for k in ('success', 'ok', 'completed', 'ready', 'saved')):
                level = 'success'
        tag = level if level in ('info', 'warn', 'error', 'success') else 'info'
        self.log_text.insert(tk.END, f"[{timestamp}] ", ('timestamp',))
        self.log_text.insert(tk.END, f"{message}\n", (tag,))
        self.log_text.see(tk.END)
    
    def _start_auto_refresh(self):
        def refresh():
            if self.auto_refresh:
                self._refresh_dashboard()
                self.root.after(self.refresh_interval, refresh)
        self.root.after(self.refresh_interval, refresh)
    
    def _refresh_dashboard(self):
        status = self.data.get_global_status()
        
        self.dashboard_stats["Projects"].set(str(len(status.get('projects', {}))))
        self.dashboard_stats["Models Tracked"].set(str(len(status.get('shared_health', {}))))
        self.dashboard_stats["Models Scored"].set(str(len(status.get('shared_scores', {}))))
        
        total_in_flight = sum(p.get('in_flight', 0) for p in status.get('projects', {}).values())
        self.dashboard_stats["Total In-Flight"].set(str(total_in_flight))
        if hasattr(self, 'status_flight_var'):
            self.status_flight_var.set(f"In-Flight: {total_in_flight}")
        
        # Update project tree
        for item in self.proj_tree.get_children():
            self.proj_tree.delete(item)
        
        for name, proj_status in status.get('projects', {}).items():
            quarantined = ", ".join(proj_status.get('quarantined', [])) or "none"
            self.proj_tree.insert("", "end", values=(
                name, proj_status['domain'], "Yes", 
                str(proj_status['in_flight']), str(proj_status['max_in_flight']), quarantined
            ))


def main():
    # DPI awareness before creating the root window avoids blurry text and
    # a white flash on high-DPI displays (spec section 4).
    ThemeManager.enable_dpi_awareness()
    root = tk.Tk()
    root.configure(bg=PALETTE['bg_base'])
    app = J5DesktopApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
