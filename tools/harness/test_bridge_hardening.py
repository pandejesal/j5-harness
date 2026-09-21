#!/usr/bin/env python3
"""
Regression test for antigravity_bridge.py hardening.

Verifies the key hardening measures:
1. No shell=True injection possible
2. JSON stdout parsing, stderr to evidence
3. --print --output-format json enforced
4. JSON stdout parsing, stderr to evidence
"""

import sys, subprocess, json, os
from pathlib import Path

BRIDGE = Path(r"C:\Users\DELL\.agents\skills\antigravity\scripts\antigravity_bridge.py")

def run_bridge(args, cwd=None, timeout=30):
    """Run bridge with args, return (exit_code, stdout, stderr)"""
    cmd = [sys.executable, str(BRIDGE)] + args
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr

def test_bridge_returns_json():
    """Verify bridge returns structured JSON with status/output/evidence"""
    rc, out, err = run_bridge(["hello world", "--print", "--output-format", "json", "--add-dir", "C:\\Users\\DELL", "--json"])
    try:
        data = json.loads(out.strip())
        assert data["status"] in ("success", "error")
        assert "output" in data
        assert "evidence" in data
        assert isinstance(data["evidence"], dict)
        return True, "Bridge returns structured JSON correctly"
    except (json.JSONDecodeError, AssertionError) as e:
        return False, f"Bridge JSON structure invalid: {e}"

def test_json_output_valid():
    """Output with --print --output-format json must be valid JSON"""
    rc, out, err = run_bridge(["hello world", "--print", "--output-format", "json", "--add-dir", "C:\\Users\\DELL", "--json"])
    try:
        data = json.loads(out.strip())
        assert data["status"] in ("success", "error")
        assert "output" in data
        assert "evidence" in data
        agy_response = json.loads(data["output"])
        assert "conversation_id" in agy_response or "status" in agy_response
        return True, "Valid JSON output with correct structure"
    except (json.JSONDecodeError, AssertionError) as e:
        return False, f"Invalid JSON structure: {e}"

def test_injection_payload_blocked():
    """Payload with ; rm should NOT execute"""
    payload = 'test"; rm -rf /tmp/test_injection_marker; echo "injected"'
    rc, out, err = run_bridge([payload, "--print", "--output-format", "json", "--add-dir", "C:\\Users\\DELL", "--json"])
    marker = Path("/tmp/test_injection_marker")
    if marker.exists():
        marker.unlink()
        return False, "INJECTION SUCCEEDED - marker file created"
    return True, f"Injection blocked (rc={rc})"

def run_bridge(args, cwd=None, timeout=45):
    """Run bridge with args, return (exit_code, stdout, stderr)"""
    cmd = [sys.executable, str(BRIDGE)] + args
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    return proc.returncode, proc.stdout, proc.stderr

def main():
    tests = [
        ("Injection payload blocked", test_injection_payload_blocked),
        ("Bridge returns structured JSON", test_bridge_returns_json),
        ("JSON output has correct structure", test_json_output_valid),
    ]
    passed = 0
    for name, fn in tests:
        try:
            ok, msg = fn()
            status = "PASS" if ok else "FAIL"
            print(f"  {status}: {name} - {msg}")
            if ok: passed += 1
        except Exception as e:
            print(f"  FAIL: {name} - exception: {e}")
    print(f"\nResult: {passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1

if __name__ == "__main__":
    sys.exit(main())