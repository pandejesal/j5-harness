"""Mutation-boundary regression tests: lazy imports + readonly guard.

1. Read-only CLI commands (`route`, `status`, ...) must not create files or
   directories as a side effect — verified in a FRESH interpreter
   (subprocess), because in-process tests cannot observe import-time
   side effects.
2. Readonly mode (`--readonly` flag or ``J5_READONLY=1``) must refuse
   mutating commands with exit code 2 before anything executes, while
   read-only commands keep working.
3. `j5 capabilities` exposes the boundary map (JSON + table).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _snapshot(path: Path) -> set[str]:
    """Relative names of everything under *path* (files and dirs)."""
    if not path.exists():
        return set()
    return {str(p.relative_to(path)) for p in path.rglob("*")}


def _run_cli(*argv: str, timeout: int = 180) -> subprocess.CompletedProcess:
    """Run the CLI in a fresh interpreter (clean env: never readonly)."""
    env = {k: v for k, v in os.environ.items() if k != "J5_READONLY"}
    return subprocess.run(
        [sys.executable, "-m", "j5_cli.main", *argv],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


class NoSideEffectTest(unittest.TestCase):
    """Read commands must not create files/dirs — fresh interpreter each time.

    NOTE: these snapshot assertions assume no concurrent j5 writer (kilo
    watcher, parallel `j5 run`) on this machine between the before/after
    snapshots. A concurrent writer to the tracker dir or tools/state/
    would produce a false failure; run boundary tests serially.
    """

    def test_route_and_status_create_nothing(self):
        from tools.harness.watch_kilo import TRACKER_DIR

        state_dir = PROJECT_ROOT / "tools" / "state"
        for argv in (["route"], ["status"]):
            before_state = _snapshot(state_dir)
            before_tracker = _snapshot(TRACKER_DIR)
            proc = _run_cli(*argv)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
            self.assertEqual(
                _snapshot(state_dir), before_state,
                msg=f"`j5 {' '.join(argv)}` created files under tools/state/",
            )
            self.assertEqual(
                _snapshot(TRACKER_DIR), before_tracker,
                msg=f"`j5 {' '.join(argv)}` created files under the InterHarness tracker",
            )

    def test_help_creates_nothing(self):
        from tools.harness.watch_kilo import TRACKER_DIR

        state_dir = PROJECT_ROOT / "tools" / "state"
        before_state = _snapshot(state_dir)
        before_tracker = _snapshot(TRACKER_DIR)
        proc = _run_cli("--help")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr[-2000:])
        self.assertIn("readonly", proc.stdout.lower())
        self.assertEqual(_snapshot(state_dir), before_state)
        self.assertEqual(_snapshot(TRACKER_DIR), before_tracker)


class ReadonlyTest(unittest.TestCase):
    """Readonly mode refuses mutating commands (exit 2) before execution."""

    def test_env_run_refused_without_executing(self):
        import j5_cli.main as cli

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            witness = MagicMock()
            with unittest.mock.patch.object(cli, "make_router_fn", witness):
                rc = cli.main(["run", "--project", "wsb-alpha",
                               "--task-type", "coding", "--prompt", "x"])
        self.assertEqual(rc, 2)
        witness.assert_not_called()

    def test_env_probe_refused_without_executing(self):
        import j5_cli.main as cli

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            witness = MagicMock()
            with unittest.mock.patch.object(cli, "run_probe_roundtrip", witness):
                rc = cli.main(["probe", "--project", "wsb-alpha",
                               "--probe-id", "probe-x", "--prompt", "x"])
        self.assertEqual(rc, 2)
        witness.assert_not_called()

    def test_env_watch_refused_without_executing(self):
        import j5_cli.main as cli
        import tools.harness.watch_kilo as wk

        called: list[str] = []

        def fake_process_once():
            # If the gate ever fails, fail fast instead of looping forever.
            called.append("watch_once")
            raise KeyboardInterrupt

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            with unittest.mock.patch.object(wk, "process_once", fake_process_once):
                rc = cli.main(["watch", "--interval", "1"])
        self.assertEqual(rc, 2)
        self.assertEqual(called, [])

    def test_env_bare_j5_refused(self):
        # Bare `j5` opens the TUI, which spawns workers -> blocked too.
        import j5_cli.main as cli

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            rc = cli.main([])
        self.assertEqual(rc, 2)

    def test_env_status_still_succeeds(self):
        import j5_cli.main as cli

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            rc = cli.main(["status"])
        self.assertEqual(rc, 0)

    def test_flag_run_refused(self):
        import j5_cli.main as cli

        env = {k: v for k, v in os.environ.items() if k != "J5_READONLY"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            witness = MagicMock()
            with unittest.mock.patch.object(cli, "make_router_fn", witness):
                rc = cli.main(["--readonly", "run", "--project", "wsb-alpha",
                               "--task-type", "coding", "--prompt", "x"])
        self.assertEqual(rc, 2)
        witness.assert_not_called()

    def test_flag_status_still_succeeds(self):
        import j5_cli.main as cli

        env = {k: v for k, v in os.environ.items() if k != "J5_READONLY"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            rc = cli.main(["--readonly", "status"])
        self.assertEqual(rc, 0)

    def test_capabilities_allowed_while_locked(self):
        import j5_cli.main as cli

        with unittest.mock.patch.dict(os.environ, {"J5_READONLY": "1"}):
            rc = cli.main(["capabilities"])
        self.assertEqual(rc, 0)


class CapabilitiesCommandTest(unittest.TestCase):
    def test_map_covers_every_subcommand(self):
        # Parser/map drift is enforced inside build_parser() itself (it
        # raises ValueError on any unmapped subcommand), so constructing
        # the parser IS the coverage proof. Here we pin the known boundary.
        import j5_cli.main as cli

        cli.build_parser()
        for cmd in ("run", "probe", "watch", "tui", "capabilities",
                    "route", "status", "projects", "domains", "skills",
                    "config", "benchmark", "sessions", "doctor"):
            self.assertIn(cmd, cli.COMMAND_CAPABILITIES)

    def test_json_map(self):
        import j5_cli.main as cli
        from io import StringIO

        buf = StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = cli.main(["capabilities", "--json"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertTrue(data["run"]["spawns_worker"])
        self.assertTrue(data["run"]["mutates_project"])
        self.assertFalse(data["route"]["spawns_worker"])
        self.assertFalse(data["status"]["mutates_harness_state"])
        self.assertIn("capabilities", data)
        self.assertIn("tui", data)

    def test_table_lists_every_command(self):
        import j5_cli.main as cli
        from io import StringIO

        buf = StringIO()
        old = sys.stdout
        try:
            sys.stdout = buf
            rc = cli.main(["capabilities"])
        finally:
            sys.stdout = old
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        for cmd in ("run", "probe", "watch", "route", "status", "tui",
                    "capabilities", "sessions"):
            self.assertIn(cmd, out)

    def test_sessions_lists_recorded_turns(self):
        import j5_cli.main as cli

        env = {k: v for k, v in os.environ.items() if k != "J5_READONLY"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            rc = cli.main(["sessions", "--limit", "5"])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
