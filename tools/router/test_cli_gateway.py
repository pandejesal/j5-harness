"""Unit tests for tools.router.cli_gateway (mocked subprocess only).

No worker CLI is invoked: subprocess.run, PATH lookup, and filesystem
checks are all mocked. A live end-to-end proof lives outside this file
(`j5 run --prompt "Reply with exactly: J5_OK"` against real opencode).
"""

from __future__ import annotations

import io
import json
import subprocess
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.router.cli_gateway import (
    MODEL_MAP,
    OpencodeCliAdapter,
    classify_cli_failure,
    cli_model_id,
    extract_opencode_text,
    find_opencode_binary,
)
from tools.router.gateway_adapters import GatewayError


def _completed(stdout: str = "", stderr: str = "", returncode: int = 0):
    return subprocess.CompletedProcess(args=["opencode"], returncode=returncode,
                                       stdout=stdout, stderr=stderr)


def _json_stream(texts, finish_reason="stop"):
    lines = [
        json.dumps({"type": "step_start", "sessionID": "ses_test"}),
    ]
    for i, t in enumerate(texts):
        lines.append(json.dumps({
            "type": "text",
            "sessionID": "ses_test",
            "part": {"id": f"prt_{i}", "messageID": "msg_1",
                     "sessionID": "ses_test", "type": "text", "text": t},
        }))
    lines.append(json.dumps({
        "type": "step_finish",
        "sessionID": "ses_test",
        "part": {"id": "prt_f", "messageID": "msg_1", "sessionID": "ses_test",
                 "type": "step-finish", "reason": finish_reason,
                 "tokens": {"total": 100, "input": 90, "output": 10}},
    }))
    return "\n".join(lines)


class CliModelIdTest(unittest.TestCase):
    def test_plain_id_gets_prefix(self):
        self.assertEqual(cli_model_id("mimo-v2.5-free"), "opencode/mimo-v2.5-free")

    def test_slashed_id_passes_through(self):
        self.assertEqual(cli_model_id("opencode/mimo-v2.5-free"), "opencode/mimo-v2.5-free")
        self.assertEqual(cli_model_id("otherprov/some-model"), "otherprov/some-model")

    def test_explicit_map_wins(self):
        with patch.dict(MODEL_MAP, {"laguna-s-2.1-free": "opencode-go/laguna-x"}):
            self.assertEqual(cli_model_id("laguna-s-2.1-free"), "opencode-go/laguna-x")

    def test_custom_prefix(self):
        self.assertEqual(cli_model_id("hy3-free", prefix="opencode-go"), "opencode-go/hy3-free")


class ExtractTextTest(unittest.TestCase):
    def test_folds_text_events(self):
        text, usage = extract_opencode_text(_json_stream(["J5", "_OK"]))
        self.assertEqual(text, "J5_OK")
        self.assertEqual(usage["session_id"], "ses_test")
        self.assertEqual(usage["tokens_total"], 100)
        self.assertEqual(usage["finish_reason"], "stop")

    def test_empty_stream(self):
        text, usage = extract_opencode_text("")
        self.assertEqual(text, "")
        self.assertEqual(usage, {})

    def test_raw_fallback_when_no_json(self):
        text, _ = extract_opencode_text("plain answer\n")
        self.assertEqual(text, "plain answer")

    def test_malformed_lines_skipped(self):
        text, _ = extract_opencode_text("{not json\n" + _json_stream(["ok"]))
        self.assertEqual(text, "ok")


class ClassifyFailureTest(unittest.TestCase):
    def test_rate_limit(self):
        msg, code, _ = classify_cli_failure("Error: HTTP 429 too many requests", "")
        self.assertEqual(code, 429)
        self.assertIn("rate-limited", msg)

    def test_retry_after_parsed(self):
        _, code, retry = classify_cli_failure("429 retry after 42s", "")
        self.assertEqual(code, 429)
        self.assertEqual(retry, 42.0)

    def test_auth_failure(self):
        msg, code, _ = classify_cli_failure("401 unauthorized", "")
        self.assertEqual(code, 401)

    def test_generic_failure(self):
        msg, code, retry = classify_cli_failure("boom", "")
        self.assertIsNone(code)
        self.assertIsNone(retry)
        self.assertIn("boom", msg)


class FindBinaryTest(unittest.TestCase):
    def test_prefers_npm_layout(self):
        fake = Path("C:/fake/npm/node_modules/opencode-ai/bin/opencode.exe")
        with patch.dict("os.environ", {"APPDATA": "C:/fake", "USERPROFILE": "C:/fake"}), \
             patch("tools.router.cli_gateway.Path.is_file", return_value=True), \
             patch("tools.router.cli_gateway.shutil.which", return_value=None):
            self.assertEqual(find_opencode_binary(), str(fake))

    def test_none_when_absent(self):
        with patch("tools.router.cli_gateway.Path.is_file", return_value=False), \
             patch("tools.router.cli_gateway.shutil.which", return_value=None):
            self.assertIsNone(find_opencode_binary())


class FakeStdout:
    """Iterable stdout for FakePopen (plain list of lines)."""

    def __init__(self, lines):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class HangingStdout:
    """Blocks until the proc is killed, emulating a stuck worker."""

    def __init__(self, proc):
        self._proc = proc

    def __iter__(self):
        return self

    def __next__(self):
        for _ in range(10000):
            if self._proc.killed:
                raise StopIteration
            time.sleep(0.002)
        raise StopIteration


class FakePopen:
    def __init__(self, lines=(), returncode=0, stderr="", hanging=False):
        self.killed = False
        self._hanging = hanging
        self._lines = list(lines)
        self.stdout = None  # wired below (needs self)
        self.stderr = io.StringIO(stderr)
        self.returncode = returncode
        self.stdout = HangingStdout(self) if hanging else FakeStdout(self._lines)

    def wait(self):
        return -9 if self.killed else self.returncode

    def kill(self):
        self.killed = True


class AdapterSendTest(unittest.TestCase):
    def _adapter(self):
        return OpencodeCliAdapter(binary="C:/fake/opencode.exe", workdir="C:/fake/wd")

    def _popen(self, *args, **kwargs):
        raise AssertionError("patch me per-test")

    def test_success_returns_output(self):
        adapter = self._adapter()
        fake = FakePopen(_json_stream(["J5_OK"]).splitlines(keepends=True))
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake) as m:
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                result = adapter.send("mimo-v2.5-free", "hi", workdir="C:/proj", task_id="task-1")
        self.assertEqual(result["output"], "J5_OK")
        self.assertEqual(result["model"], "opencode/mimo-v2.5-free")
        cmd = m.call_args[0][0]
        self.assertIn("-m", cmd)
        self.assertIn("opencode/mimo-v2.5-free", cmd)
        self.assertIn("--format", cmd)
        self.assertIn("json", cmd)
        self.assertIn("j5-task-1", cmd)  # title carries the task id
        self.assertIs(m.call_args[1]["stdin"], subprocess.DEVNULL)  # never hang on prompts

    def test_on_text_streams_chunks_live(self):
        adapter = self._adapter()
        fake = FakePopen(_json_stream(["hel", "lo"]).splitlines(keepends=True))
        seen: list[str] = []
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake):
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                result = adapter.send("mimo-v2.5-free", "hi", on_text=seen.append)
        self.assertEqual(seen, ["hel", "lo"])
        self.assertEqual(result["output"], "hello")

    def test_session_id_continues_worker_session(self):
        adapter = self._adapter()
        fake = FakePopen(_json_stream(["ok"]).splitlines(keepends=True))
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake) as m:
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                adapter.send("mimo-v2.5-free", "follow-up", session_id="ses_abc123")
        cmd = m.call_args[0][0]
        self.assertIn("--session", cmd)
        self.assertIn("ses_abc123", cmd)

    def test_empty_output_raises(self):
        adapter = self._adapter()
        fake = FakePopen([], returncode=1, stderr="it broke")
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake):
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                with self.assertRaises(GatewayError):
                    adapter.send("mimo-v2.5-free", "hi")

    def test_rate_limit_maps_to_429(self):
        adapter = self._adapter()
        fake = FakePopen([], returncode=1, stderr="HTTP 429 slow down")
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake):
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                with self.assertRaises(GatewayError) as ctx:
                    adapter.send("mimo-v2.5-free", "hi")
        self.assertEqual(ctx.exception.status_code, 429)

    def test_timeout_raises(self):
        adapter = self._adapter()
        fake = FakePopen(hanging=True)
        with patch("tools.router.cli_gateway.subprocess.Popen", return_value=fake):
            with patch("tools.router.cli_gateway.Path.is_dir", return_value=True):
                with self.assertRaises(GatewayError) as ctx:
                    adapter.send("mimo-v2.5-free", "hi", timeout_s=0.05)
        self.assertIn("timed out", str(ctx.exception))

    def test_terminate_current_kills_proc(self):
        adapter = self._adapter()
        fake = FakePopen(hanging=True)
        with self.assertRaises(AttributeError):
            fake.no_such_attr  # sanity: fake is minimal
        adapter._current_proc = fake  # type: ignore[assignment]
        adapter.terminate_current()
        self.assertTrue(fake.killed)
        adapter._current_proc = None
        adapter.terminate_current()  # no proc -> no-op, no raise

    def test_missing_binary_raises_value_error(self):
        with patch("tools.router.cli_gateway.find_opencode_binary", return_value=None):
            with self.assertRaises(ValueError):
                OpencodeCliAdapter(binary=None)

    def test_busy_adapter_refuses_second_dispatch(self):
        import asyncio

        adapter = self._adapter()
        adapter._in_flight = 1
        with self.assertRaises(GatewayError):
            asyncio.run(adapter.asend("mimo-v2.5-free", "hi"))


class BuildGatewayTest(unittest.TestCase):
    def test_zen_forced_by_env(self):
        from tools.harness.integration import build_gateway
        from tools.router.gateway_adapters import ZenGatewayAdapter

        with patch.dict("os.environ", {"J5_GATEWAY": "zen"}):
            self.assertIsInstance(build_gateway(), ZenGatewayAdapter)

    def test_cli_forced_by_env(self):
        from tools.harness.integration import build_gateway

        with patch.dict("os.environ", {"J5_GATEWAY": "cli"}), \
             patch("tools.router.cli_gateway.find_opencode_binary",
                   return_value="C:/fake/opencode.exe"):
            gw = build_gateway()
        self.assertIsInstance(gw, OpencodeCliAdapter)

    def test_auto_prefers_cli_when_present(self):
        from tools.harness.integration import build_gateway

        with patch.dict("os.environ", {"J5_GATEWAY": "auto"}), \
             patch("tools.router.cli_gateway.find_opencode_binary",
                   return_value="C:/fake/opencode.exe"):
            gw = build_gateway()
        self.assertIsInstance(gw, OpencodeCliAdapter)

    def test_auto_falls_back_to_zen(self):
        from tools.harness.integration import build_gateway
        from tools.router.gateway_adapters import ZenGatewayAdapter

        with patch.dict("os.environ", {"J5_GATEWAY": "auto"}), \
             patch("tools.router.cli_gateway.find_opencode_binary", return_value=None):
            gw = build_gateway()
        self.assertIsInstance(gw, ZenGatewayAdapter)


if __name__ == "__main__":
    unittest.main()
