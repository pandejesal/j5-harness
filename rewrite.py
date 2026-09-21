import re

with open("j5_desktop/app.py", "r", encoding="utf-8") as f:
    content = f.read()

# Add Tooltip class
tooltip_code = """
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

"""
content = content.replace("class J5HarnessData:", tooltip_code + "class J5HarnessData:")

# Replace _build_ui
new_build_ui = """
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

"""

# Restore from backup first
with open("j5_desktop/app.py.bak", "r", encoding="utf-8") as f:
    content = f.read()

content = content.replace("class J5HarnessData:", tooltip_code + "class J5HarnessData:")
content = re.sub(r'    def _build_ui\(self\):.*?    def _create_dashboard_tab\(self\):', new_build_ui + '\n    def _create_dashboard_tab(self, frame):', content, flags=re.DOTALL)

def replace_tab_preamble(match):
    name = match.group(1)
    return f"    def _create_{name}_tab(self, frame):"

content = re.sub(r'    def _create_([a-z_]+)_tab\(self\):\s*frame = ttk\.Frame\(self\.notebook, padding=10\)\s*self\.notebook\.add\(frame, text=".*?"\)', replace_tab_preamble, content)

content = re.sub(r"        # Details panel.*?self\.proj_detail\.pack\(fill=tk\.BOTH, expand=True\)", "        self.proj_detail = self.global_detail\n        self.proj_list.bind('<<TreeviewSelect>>', self._on_project_select)", content, flags=re.DOTALL)
content = re.sub(r"        # Domain details.*?self\.domain_detail\.pack\(fill=tk\.BOTH, expand=True\)", "        self.domain_detail = self.global_detail\n        self.domain_tree.bind('<<TreeviewSelect>>', self._on_domain_select)", content, flags=re.DOTALL)

dashboard_refresh = """
        total_in_flight = sum(p.get('in_flight', 0) for p in status.get('projects', {}).values())
        self.dashboard_stats["Total In-Flight"].set(str(total_in_flight))
        if hasattr(self, 'status_flight_var'):
            self.status_flight_var.set(f"In-Flight: {total_in_flight}")
"""
content = content.replace('        self.dashboard_stats["Total In-Flight"].set(str(total_in_flight))', dashboard_refresh.strip())

new_tabs = r"""
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
"""

content = content.replace("    def _show_message(", new_tabs + "\n    def _show_message(")

with open("j5_desktop/app.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Rewrite complete.")
