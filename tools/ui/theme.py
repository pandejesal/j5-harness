"""Shared black-theme tokens for the J5 Harness UI surfaces.

Single source of truth for the black theme defined in
``.swarm/spec-ui-black-theme.md`` (sections 1-3, 5-7):

- ``PALETTE``: hex color tokens (deep blacks, subtle borders, accents).
- ``FONT``: desktop font stack (Segoe UI / Cascadia Code / Cascadia Mono).
- ``ANSI``: raw escape sequences for CLI output (no colorama, no deps).
- ``ThemeManager``: tkinter/ttk theming (clam base, dark titlebar, DPI).
- CLI helpers: ``color``, ``status_line``, ``progress_bar``, ``ok_line``,
  ``fail_line``, ``hint``, ``title``, ``separator``.
- TUI helpers: ``textual_css`` (Textual CSS tokens) and ``curses_pairs``
  (curses color-pair table).

Stdlib-only, Python 3.12, Windows compatible.
"""

from __future__ import annotations

import os
import sys
from typing import Any

__version__ = "1.0.0"

# ---------------------------------------------------------------------------
# 1. Palette tokens (single source of truth)
# ---------------------------------------------------------------------------

PALETTE: dict[str, str] = {
    # Surfaces
    "bg_base": "#010409",
    "bg_panel": "#0d1117",
    "bg_elevated": "#161b22",
    "bg_hover": "#1c2128",
    "bg_selected": "#1f3a5f",
    # Borders
    "border": "#30363d",
    "border_subtle": "#21262d",
    "border_focus": "#58a6ff",
    # Text
    "text": "#e6edf3",
    "text_muted": "#8b949e",
    "text_dim": "#484f58",
    # Accents
    "accent_blue": "#58a6ff",
    "success": "#3fb950",
    "warning": "#d29922",
    "error": "#f85149",
    "purple": "#bc8cff",
    "cyan": "#39d2c0",
}

# ---------------------------------------------------------------------------
# 2. Typography
# ---------------------------------------------------------------------------

FONT: dict[str, tuple[str, int] | tuple[str, ...]] = {
    "ui": ("Segoe UI", 10),
    "code": ("Cascadia Code", 11),
    "code_fallback": ("Consolas", "Courier New"),
    "mono": ("Cascadia Mono", 10),
}

# ---------------------------------------------------------------------------
# 3. ANSI escapes (CLI, raw, no colorama)
# ---------------------------------------------------------------------------


class ANSI:
    """Raw ANSI escape sequences for CLI output (spec section 6).

    BOLD/DIM, FG 252/245/238/75/71/179/203/80, BG 233/234/235.
    """

    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"

    # Foreground (256-color palette)
    FG_252 = "\x1b[38;5;252m"  # text
    FG_245 = "\x1b[38;5;245m"  # muted
    FG_238 = "\x1b[38;5;238m"  # dim
    FG_75 = "\x1b[38;5;75m"    # accent blue
    FG_71 = "\x1b[38;5;71m"    # success green
    FG_179 = "\x1b[38;5;179m"  # warning yellow
    FG_203 = "\x1b[38;5;203m"  # error red
    FG_80 = "\x1b[38;5;80m"    # cyan

    # Background
    BG_233 = "\x1b[48;5;233m"
    BG_234 = "\x1b[48;5;234m"
    BG_235 = "\x1b[48;5;235m"

    # Named aliases
    TEXT = FG_252
    MUTED = FG_245
    DIM_FG = FG_238
    ACCENT = FG_75
    SUCCESS = FG_71
    WARNING = FG_179
    ERROR = FG_203
    CYAN = FG_80
    BG_BASE = BG_233
    BG_PANEL = BG_234
    BG_ELEVATED = BG_235


# ---------------------------------------------------------------------------
# 4. CLI helpers (spec section 6)
# ---------------------------------------------------------------------------


def supports_color(stream: Any = None) -> bool:
    """True when ANSI color should be emitted for *stream*.

    Disabled when ``NO_COLOR`` is set (any value) or the stream is not a
    TTY (spec section 7: plain fallback).
    """
    if os.environ.get("NO_COLOR") is not None:
        return False
    if stream is None:
        stream = sys.stdout
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError):
        return False


def color(text: str, code: str = ANSI.TEXT, *, enabled: bool | None = None) -> str:
    """Wrap *text* in *code* + reset; plain *text* when color is disabled."""
    if enabled is None:
        enabled = supports_color()
    if not enabled:
        return text
    return f"{code}{text}{ANSI.RESET}"


def status_line(ok: bool, text: str, *, enabled: bool | None = None) -> str:
    """Green check / red cross prefix followed by *text*."""
    mark = color("✓", ANSI.SUCCESS, enabled=enabled) if ok else color("✗", ANSI.ERROR, enabled=enabled)
    return f"{mark} {text}"


def progress_bar(fraction: float, width: int = 24, *, enabled: bool | None = None) -> str:
    """Yellow progress bar with percentage, e.g. ``[██████░░░░] 50%``."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * width)
    bar = "█" * filled + "░" * (width - filled)
    pct = f"{fraction * 100:3.0f}%"
    return f"{color(bar, ANSI.WARNING, enabled=enabled)} {pct}"


def ok_line(text: str, *, enabled: bool | None = None) -> str:
    """Green check line."""
    return status_line(True, text, enabled=enabled)


def fail_line(text: str, *, enabled: bool | None = None) -> str:
    """Red cross line."""
    return status_line(False, text, enabled=enabled)


def hint(text: str, *, enabled: bool | None = None) -> str:
    """Dim hint line."""
    return color(text, ANSI.MUTED, enabled=enabled)


def title(text: str, *, enabled: bool | None = None) -> str:
    """Bold cyan title."""
    if enabled is None:
        enabled = supports_color()
    if not enabled:
        return text
    return f"{ANSI.BOLD}{ANSI.ACCENT}{text}{ANSI.RESET}"


def separator(text: str = "", width: int = 60, *, enabled: bool | None = None) -> str:
    """Dim separator line, optionally with a centered label."""
    if enabled is None:
        enabled = supports_color()
    if text:
        pad = max(0, (width - len(text) - 2) // 2)
        line = "─" * pad + f" {text} " + "─" * (width - pad - len(text) - 2)
    else:
        line = "─" * width
    if not enabled:
        return line
    return f"{ANSI.DIM}{line}{ANSI.RESET}"


# ---------------------------------------------------------------------------
# 5. TUI helpers (spec section 5)
# ---------------------------------------------------------------------------


def textual_css() -> str:
    """Textual CSS tokens for the TUI dashboard (spec section 5)."""
    return f"""\
Screen {{
    background: {PALETTE["bg_base"]};
    color: {PALETTE["text"]};
}}
Sidebar {{
    background: {PALETTE["bg_panel"]};
    border-right: tall {PALETTE["border"]};
}}
DataTable > .datatable--cursor {{
    background: {PALETTE["accent_blue"]};
}}
Input {{
    background: {PALETTE["bg_base"]};
    border: {PALETTE["border"]};
}}
Input:focus {{
    border: {PALETTE["accent_blue"]};
}}
Log {{
    background: {PALETTE["bg_base"]};
    color: {PALETTE["text"]};
}}
"""


# curses color constants (stable across implementations; the ``curses``
# module itself is unavailable on Windows, so keep the numbers local).
_CURSES_COLORS: dict[str, int] = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "magenta": 5,
    "cyan": 6,
    "white": 7,
}


def curses_pairs() -> dict[str, tuple[int, int]]:
    """Curses color-pair table: name -> (fg, bg) (spec section 5)."""
    c = _CURSES_COLORS
    return {
        "text": (c["white"], c["black"]),
        "selection": (c["black"], c["blue"]),
        "accent": (c["cyan"], c["black"]),
        "warn": (c["yellow"], c["black"]),
        "error": (c["red"], c["black"]),
        "success": (c["green"], c["black"]),
    }


def init_curses_pairs(stdscr: Any) -> dict[str, int]:
    """Register the pairs with curses and return name -> pair number.

    POSIX only (``curses`` is unavailable on Windows); call after
    ``curses.start_color()``.
    """
    import curses

    registered: dict[str, int] = {}
    for number, (name, (fg, bg)) in enumerate(curses_pairs().items(), start=1):
        try:
            curses.init_pair(number, fg, bg)
        except curses.error:
            continue
        registered[name] = number
    return registered


# ---------------------------------------------------------------------------
# 6. Desktop (tkinter) theming
# ---------------------------------------------------------------------------


class ThemeManager:
    """tkinter/ttk black-theme manager.

    Uses the ``clam`` base theme only (never the native/default theme).
    tkinter is imported lazily so the module stays importable in pure
    CLI/TUI contexts without a display.
    """

    def __init__(self, root: Any = None) -> None:
        from tkinter import ttk

        self._ttk = ttk
        self.root: Any = root
        self.style: Any = None
        if root is not None:
            self.style = ttk.Style(root)
            self.style.theme_use("clam")

    # -- platform setup -------------------------------------------------

    @staticmethod
    def enable_dpi_awareness() -> None:
        """Best-effort per-monitor DPI awareness (Windows only, no-op elsewhere)."""
        if sys.platform != "win32":
            return
        try:
            import ctypes

            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 == (HANDLE)-4
            if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
                return
        except (AttributeError, OSError):
            pass
        try:
            import ctypes

            # PROCESS_PER_MONITOR_DPI_AWARE == 2
            if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
                return
        except (AttributeError, OSError):
            pass
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass

    @staticmethod
    def set_dark_titlebar(hwnd: int) -> None:
        """Enable the dark titlebar via DwmSetWindowAttribute (Windows 10 1903+)."""
        if sys.platform != "win32" or not hwnd:
            return
        try:
            import ctypes

            value = ctypes.c_int(1)
            # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 (1903+) / 19 (pre-1903)
            for attr in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    ctypes.c_void_p(hwnd),
                    attr,
                    ctypes.byref(value),
                    ctypes.sizeof(value),
                )
                if result == 0:  # S_OK
                    return
        except (AttributeError, OSError):
            pass

    # -- ttk style configuration ----------------------------------------

    def configure_buttons(self) -> None:
        """Flat dark buttons, 12x6 padding (spec section 4)."""
        if self.style is None:
            return
        self.style.configure(
            "TButton",
            background=PALETTE["bg_elevated"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["bg_elevated"],
            darkcolor=PALETTE["bg_elevated"],
            focuscolor=PALETTE["border_focus"],
            relief="flat",
            padding=(12, 6),
        )
        self.style.map(
            "TButton",
            background=[
                ("pressed", PALETTE["bg_selected"]),
                ("active", PALETTE["bg_hover"]),
            ],
            foreground=[("disabled", PALETTE["text_dim"])],
        )

    def configure_treeview(self) -> None:
        """Dark treeview: rowheight 28, no gridlines, selected bg_selected."""
        if self.style is None:
            return
        self.style.configure(
            "Treeview",
            background=PALETTE["bg_base"],
            fieldbackground=PALETTE["bg_base"],
            foreground=PALETTE["text"],
            bordercolor=PALETTE["border"],
            relief="flat",
            rowheight=28,
        )
        self.style.map(
            "Treeview",
            background=[("selected", PALETTE["bg_selected"])],
            foreground=[("selected", PALETTE["text"])],
        )
        self.style.configure(
            "Treeview.Heading",
            background=PALETTE["bg_elevated"],
            foreground=PALETTE["text_muted"],
            relief="flat",
            padding=(6, 4),
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", PALETTE["bg_hover"])],
        )

    def configure_entry(self) -> None:
        """Dark entry: bg_base, 1px border, 2px focus border_focus."""
        if self.style is None:
            return
        self.style.configure(
            "TEntry",
            background=PALETTE["bg_base"],
            fieldbackground=PALETTE["bg_base"],
            foreground=PALETTE["text"],
            insertcolor=PALETTE["text"],
            bordercolor=PALETTE["border"],
            lightcolor=PALETTE["border"],
            darkcolor=PALETTE["border"],
            relief="flat",
            padding=(6, 8),
        )
        self.style.map(
            "TEntry",
            bordercolor=[("focus", PALETTE["border_focus"])],
            lightcolor=[("focus", PALETTE["border_focus"])],
            darkcolor=[("focus", PALETTE["border_focus"])],
        )

    def configure_notebook(self) -> None:
        """Dark notebook: inactive text_muted, active text + accent border."""
        if self.style is None:
            return
        self.style.configure(
            "TNotebook",
            background=PALETTE["bg_panel"],
            bordercolor=PALETTE["border"],
            borderwidth=0,
            relief="flat",
            tabmargins=(0, 0, 0, 0),
        )
        self.style.configure(
            "TNotebook.Tab",
            background=PALETTE["bg_panel"],
            foreground=PALETTE["text_muted"],
            bordercolor=PALETTE["border"],
            padding=(12, 6),
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", PALETTE["bg_elevated"])],
            foreground=[("selected", PALETTE["text"])],
            # Approximates the 2px bottom accent on the active tab.
            bordercolor=[("selected", PALETTE["border_focus"])],
        )

    def configure_scrollbar(self) -> None:
        """Thin dark scrollbar: width 8, trough bg_base, arrowsize 0."""
        if self.style is None:
            return
        for orient in ("Vertical", "Horizontal"):
            self.style.configure(
                f"{orient}.TScrollbar",
                background=PALETTE["bg_elevated"],
                troughcolor=PALETTE["bg_base"],
                bordercolor=PALETTE["bg_base"],
                relief="flat",
                arrowsize=0,
                width=8,
            )
            self.style.map(
                f"{orient}.TScrollbar",
                background=[("active", PALETTE["bg_hover"])],
            )

    def configure_labelframe(self) -> None:
        """Dark labelframe: bg_panel body, muted label."""
        if self.style is None:
            return
        self.style.configure(
            "TLabelframe",
            background=PALETTE["bg_panel"],
            bordercolor=PALETTE["border"],
            relief="flat",
        )
        self.style.configure(
            "TLabelframe.Label",
            background=PALETTE["bg_panel"],
            foreground=PALETTE["text_muted"],
        )

    def configure_all(self) -> None:
        """Apply every ttk style configuration."""
        self.configure_buttons()
        self.configure_treeview()
        self.configure_entry()
        self.configure_notebook()
        self.configure_scrollbar()
        self.configure_labelframe()

    # -- tk classic defaults --------------------------------------------

    def option_add_defaults(self) -> None:
        """tk classic widget defaults via ``option_add`` (spec section 4)."""
        if self.root is None:
            return
        opt = self.root.option_add
        opt("*Background", PALETTE["bg_panel"])
        opt("*Foreground", PALETTE["text"])
        opt("*selectBackground", PALETTE["bg_selected"])
        opt("*selectForeground", PALETTE["text"])
        opt("*insertBackground", PALETTE["text"])
        opt("*Font", f"{{Segoe UI}} {FONT['ui'][1]}")
        opt("*Text.background", PALETTE["bg_base"])
        opt("*Text.foreground", PALETTE["text"])
        opt("*Text.highlightThickness", 0)
        opt("*Text.relief", "flat")
        opt("*Text.borderWidth", 0)
        opt("*Listbox.background", PALETTE["bg_base"])
        opt("*Listbox.foreground", PALETTE["text"])
        opt("*Listbox.highlightThickness", 0)
        opt("*Listbox.borderWidth", 0)
        opt("*Menu.background", PALETTE["bg_elevated"])
        opt("*Menu.foreground", PALETTE["text"])
        opt("*Menu.activeBackground", PALETTE["bg_selected"])
        opt("*Menu.activeForeground", PALETTE["text"])
        opt("*Entry.background", PALETTE["bg_base"])
        opt("*Entry.foreground", PALETTE["text"])
        opt("*Entry.insertBackground", PALETTE["text"])
        opt("*Entry.highlightThickness", 1)
        opt("*Entry.highlightBackground", PALETTE["border"])
        opt("*Entry.highlightColor", PALETTE["border_focus"])
        opt("*Canvas.background", PALETTE["bg_base"])
        opt("*Canvas.foreground", PALETTE["text"])

    # -- full apply -----------------------------------------------------

    def apply(self, root: Any) -> None:
        """Apply the full theme to *root*.

        Order matters: DPI awareness first, then styles and option_add
        defaults, then ``update_idletasks`` before touching the HWND for
        the dark titlebar (spec section 4).
        """
        self.enable_dpi_awareness()
        self.root = root
        self.style = self._ttk.Style(root)
        self.style.theme_use("clam")
        self.configure_all()
        self.option_add_defaults()
        root.update_idletasks()
        self.set_dark_titlebar(int(root.winfo_id()))


__all__ = [
    "__version__",
    "PALETTE",
    "FONT",
    "ANSI",
    "ThemeManager",
    "supports_color",
    "color",
    "status_line",
    "progress_bar",
    "ok_line",
    "fail_line",
    "hint",
    "title",
    "separator",
    "textual_css",
    "curses_pairs",
    "init_curses_pairs",
]