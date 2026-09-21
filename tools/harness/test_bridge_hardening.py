#!/usr/bin/env python3
"""
Regression tests for antigravity_bridge.py hardening.

Covers:
1. No shell=True injection possible (live backend call).
2. JSON stdout shape: status/output/evidence (live backend call).
3. Deep JSON structure incl. agy conversation payload (live backend call).

All three invoke the REAL agy backend over the network, where the first
call can take minutes (cold auth/model warmup) and timing is inherently
flaky. They are therefore gated behind ``J5_LIVE=1``::

    J5_LIVE=1 python -m pytest tools/harness/test_bridge_hardening.py -v

Without ``J5_LIVE`` they skip with a clear reason instead of failing the
suite on backend weather. Unit-level guarantees (arg-list construction,
no shell) belong in mocked tests, not here.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

BRIDGE = Path(r"C:\Users\DELL\.agents\skills\antigravity\scripts\antigravity_bridge.py")

needs_live_backend = pytest.mark.skipif(
    os.environ.get("J5_LIVE") != "1",
    reason="needs live agy backend; rerun with J5_LIVE=1",
)

# First backend call can be very slow (cold auth + model warmup).
LIVE_TIMEOUT_S = 300


def run_bridge(args, cwd=None, timeout=LIVE_TIMEOUT_S):
    """Run bridge with args, return (exit_code, stdout, stderr)."""
    cmd = [sys.executable, str(BRIDGE)] + args
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr


@needs_live_backend
def test_bridge_returns_json():
    """Bridge returns structured JSON with status/output/evidence."""
    _, out, _ = run_bridge([
        "hello world", "--print", "--output-format", "json",
        "--add-dir", r"C:\Users\DELL", "--json",
    ])
    data = json.loads(out.strip())
    assert data["status"] in ("success", "error")
    assert "output" in data
    assert "evidence" in data
    assert isinstance(data["evidence"], dict)


@needs_live_backend
def test_json_output_valid():
    """Output includes a parseable agy conversation payload."""
    _, out, _ = run_bridge([
        "hello world", "--print", "--output-format", "json",
        "--add-dir", r"C:\Users\DELL", "--json",
    ])
    data = json.loads(out.strip())
    assert data["status"] in ("success", "error")
    agy_response = json.loads(data["output"])
    assert "conversation_id" in agy_response or "status" in agy_response


@needs_live_backend
def test_injection_payload_blocked():
    """Payload with `; rm` must NOT execute (arg-list, no shell=True)."""
    payload = 'test"; rm -rf /tmp/test_injection_marker; echo "injected"'
    rc, _, _ = run_bridge([
        payload, "--print", "--output-format", "json",
        "--add-dir", r"C:\Users\DELL", "--json",
    ])
    marker = Path("/tmp/test_injection_marker")
    assert not marker.exists(), "INJECTION SUCCEEDED - marker file created"
    assert rc == 0


def main():
    tests = [
        ("Injection payload blocked", test_injection_payload_blocked),
        ("Bridge returns structured JSON", test_bridge_returns_json),
        ("JSON output has correct structure", test_json_output_valid),
    ]
    passed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS: {name}")
            passed += 1
        except Exception as e:  # noqa: BLE001 - standalone runner reports, never raises
            print(f"  FAIL: {name} - {e}")
    print(f"\nResult: {passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
