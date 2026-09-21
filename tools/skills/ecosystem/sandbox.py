"""Capability sandbox: policy enforcement, NOT a trust boundary.

Runs skill payloads in a dedicated worker subprocess with:
  - Win32 Job Object (kernel-enforced memory + job-time limits)
  - sys.meta_path import gate + restricted __builtins__
  - realpath+normcase filesystem gate (UNC/ADS/traversal rejected)
  - socket monkey-patch (network off by default, fail-closed)
  - sanitized environment (explicit allowlist only)

Pure-Python hooks are bypassable via introspection; the Job Object and
pre-execution review are the real controls.
"""

from __future__ import annotations

import builtins
import fnmatch
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_POLICY: dict = {
    "version": 1,
    "self_tests": {"match": [], "not_match": []},
    "filesystem": {
        "allow_reads": [],
        "allow_writes": [],
        "deny_reads": [],
        "deny_patterns": [],
    },
    "network": {"enabled": False, "allow_outbound": [], "allow_inbound": []},
    "resources": {
        "cpu": 1,
        "wall_time_ms": 30000,
        "memory_mb": 256,
        "max_threads": 32,
        "max_open_files": 256,
        "max_spawned_processes": 0,
    },
    "imports": {"deny_modules": [], "allow_modules": []},
    "builtins": {
        "exec": False,
        "eval": False,
        "compile": False,
        "__import__": False,
        "open": "restricted",
    },
    "stdio": {"capture": True, "cap": 65536},
    "env_allowlist": [],
}


def validate_policy(policy: dict) -> None:
    """Validate a policy dict, fail-closed. Raises ValueError on violation."""
    if not isinstance(policy, dict):
        raise ValueError("policy must be a dict")
    network = policy.get("network", {})
    if network.get("enabled", False):
        raise ValueError("network.enabled must be False (fail-closed)")
    builtins_cfg = policy.get("builtins", {})
    for name in ("exec", "eval", "compile"):
        if builtins_cfg.get(name, False):
            raise ValueError(f"builtins.{name} must be disabled (fail-closed)")
    if builtins_cfg.get("__import__", False):
        raise ValueError("builtins.__import__ must be disabled (fail-closed)")
    if builtins_cfg.get("open", "restricted") != "restricted":
        raise ValueError("builtins.open must be 'restricted' (fail-closed)")
    resources = policy.get("resources", {})
    wall_ms = resources.get("wall_time_ms", 30000)
    memory_mb = resources.get("memory_mb", 256)
    if not isinstance(wall_ms, int) or wall_ms <= 0:
        raise ValueError("resources.wall_time_ms must be a positive int")
    if not isinstance(memory_mb, int) or memory_mb <= 0:
        raise ValueError("resources.memory_mb must be a positive int")


def reject_reasons(path: str) -> str | None:
    """Return a rejection reason for a suspicious path, or None if clean."""
    if not isinstance(path, str) or not path:
        return "path must be a non-empty string"
    if path.startswith("\\\\") or path.startswith("//"):
        return "UNC path rejected"
    if path.startswith("\\\\?\\") or path.startswith("\\\\.\\"):
        return "device path rejected"
    # ADS: a colon anywhere except the drive-letter position.
    if ":" in path and (len(path) < 2 or path[1] != ":"):
        return "ADS/colon path rejected"
    normalized = path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if any(part == ".." or set(part) == {"."} for part in parts):
        return "parent traversal rejected"
    return None


def check_path(path: str | Path, policy: dict, access: str = "read") -> Path:
    """Resolve and gate a path against the policy filesystem rules.

    Raises PermissionError on rejection (fail-closed). Returns the
    resolved absolute path on success.
    """
    if access not in ("read", "write"):
        raise ValueError(f"access must be 'read' or 'write', got {access!r}")
    text = str(path)
    reason = reject_reasons(text)
    if reason is not None:
        raise PermissionError(f"{reason}: {text!r}")
    resolved = Path(text).resolve()
    fs = policy.get("filesystem", {})
    allow = fs.get("allow_writes" if access == "write" else "allow_reads", [])
    deny = fs.get("deny_reads", [])
    patterns = fs.get("deny_patterns", [])
    resolved_norm = os.path.normcase(str(resolved))
    allowed = False
    for entry in allow:
        entry_norm = os.path.normcase(str(Path(entry).resolve()))
        if resolved_norm == entry_norm or resolved_norm.startswith(entry_norm + os.sep):
            allowed = True
            break
    if not allowed:
        raise PermissionError(f"path outside {access} allowlist: {text!r}")
    for entry in deny:
        entry_norm = os.path.normcase(str(Path(entry).resolve()))
        if resolved_norm == entry_norm or resolved_norm.startswith(entry_norm + os.sep):
            raise PermissionError(f"path in deny list: {text!r}")
    for pattern in patterns:
        if fnmatch.fnmatch(resolved_norm, pattern) or fnmatch.fnmatch(text, pattern):
            raise PermissionError(f"path matches deny pattern {pattern!r}: {text!r}")
    return resolved


def _check_import(policy: dict, fullname: str) -> None:
    imports = policy.get("imports", {})
    deny = imports.get("deny_modules", [])
    allow = imports.get("allow_modules", [])
    if deny:
        for denied in deny:
            if fullname == denied or fullname.startswith(denied + "."):
                raise ImportError(f"module {fullname!r} denied by policy")
    if allow:
        for entry in allow:
            if fullname == entry or fullname.startswith(entry + "."):
                return
        raise ImportError(f"module {fullname!r} not in allowlist")


class _ImportGate:
    """sys.meta_path finder enforcing the imports policy."""

    def __init__(self, policy: dict) -> None:
        self.policy = policy

    def find_spec(self, fullname: str, path=None, target=None):
        _check_import(self.policy, fullname)
        return None


def install_import_gate(policy: dict) -> _ImportGate:
    """Install the meta_path import gate; returns it for reference."""
    gate = _ImportGate(policy)
    sys.meta_path.insert(0, gate)
    return gate


def _make_restricted_import(policy: dict):
    real_import = builtins.__import__

    def restricted_import(name, globals=None, locals=None, fromlist=(), level=0):
        _check_import(policy, name)
        return real_import(name, globals, locals, fromlist, level)

    return restricted_import


def _make_restricted_open(policy: dict, workdir: Path):
    real_open = builtins.open

    def restricted_open(file, mode="r", *args, **kwargs):
        if isinstance(file, (str, os.PathLike)):
            access = "write" if any(ch in mode for ch in "wax+") else "read"
            target = Path(file)
            if not target.is_absolute():
                target = workdir / target
            checked = check_path(target, policy, access)
            return real_open(checked, mode, *args, **kwargs)
        return real_open(file, mode, *args, **kwargs)

    return restricted_open


def restricted_builtins(policy: dict, workdir: Path) -> dict:
    """Build a restricted __builtins__ dict per the policy."""
    builtins_cfg = policy.get("builtins", {})
    result = dict(vars(builtins))
    for name in ("exec", "eval", "compile"):
        if builtins_cfg.get(name, False):
            raise ValueError(f"builtins.{name} must be disabled (fail-closed)")
        result.pop(name, None)
    result["__import__"] = _make_restricted_import(policy)
    result["open"] = _make_restricted_open(policy, workdir)
    return result


def patch_socket(policy: dict) -> None:
    """Monkey-patch socket entry points to fail closed when network is off."""
    network = policy.get("network", {})
    if network.get("enabled", False):
        return
    import socket as _socket

    def _denied(*_args, **_kwargs):
        raise PermissionError("network access denied by policy")

    for _name in (
        "socket",
        "create_connection",
        "create_server",
        "getaddrinfo",
        "gethostbyname",
    ):
        setattr(_socket, _name, _denied)


def sanitized_env(allowlist: list[str] | None = None) -> dict[str, str]:
    """Build a sanitized environment: only allowlisted variables survive.

    An empty/None allowlist yields an empty environment (fail-closed).
    """
    allowlist = allowlist or []
    return {key: os.environ[key] for key in allowlist if key in os.environ}


# ---------------------------------------------------------------------------
# Win32 Job Object (kernel-enforced memory + job-time limits)
# ---------------------------------------------------------------------------

_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x100
_JOB_OBJECT_LIMIT_JOB_TIME = 0x4
_JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9


def _create_job_object(memory_mb: int, job_time_ms: int) -> int:
    """Create a Win32 Job Object with memory + job-time limits. Returns handle."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
            ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.SetInformationJobObject.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.CreateJobObjectW(None, None)
    if not handle:
        raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")

    limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    flags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if memory_mb > 0:
        limits.ProcessMemoryLimit = memory_mb * 1024 * 1024
        flags |= _JOB_OBJECT_LIMIT_PROCESS_MEMORY
    if job_time_ms > 0:
        # Job time is in 100-nanosecond units.
        limits.BasicLimitInformation.PerJobUserTimeLimit = job_time_ms * 10000
        flags |= _JOB_OBJECT_LIMIT_JOB_TIME
    limits.BasicLimitInformation.LimitFlags = flags

    ok = kernel32.SetInformationJobObject(
        handle,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    )
    if not ok:
        kernel32.CloseHandle(handle)
        raise OSError(ctypes.get_last_error(), "SetInformationJobObject failed")
    return handle


def _open_process(pid: int) -> int:
    """Open a process handle with the access rights needed for job assignment."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_TERMINATE = 0x0001
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_TERMINATE | PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        pid,
    )
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    return handle


def _assign_process_to_job(job_handle: int, process_handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    if not kernel32.AssignProcessToJobObject(job_handle, process_handle):
        raise OSError(ctypes.get_last_error(), "AssignProcessToJobObject failed")


def _close_job(handle: int) -> None:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle(handle)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------

# SECURITY: _WORKER_SOURCE is the sandboxed worker program — the only place
# untrusted skill code is run. It runs exclusively inside a Popen
# subprocess (see Sandbox.run), never in the parent process, under a Win32
# Job Object with restricted __builtins__ (exec/eval/compile removed), a
# sys.meta_path import gate, a realpath+normcase filesystem gate, a
# fail-closed socket patch, and a sanitized environment. Save-then-restrict:
# the worker captures a private reference to the builtin exec before
# removing exec/eval/compile from the builtins module, then runs the payload
# through that captured reference. The parent process only writes the
# worker/payload files and spawns the worker via subprocess.Popen; it never
# executes untrusted code in-process.

_WORKER_SOURCE = r'''
"""Sandbox worker: enforce policy, then run the skill payload."""
import json
import sys
from pathlib import Path

package_root, policy_path, code_path, workdir = sys.argv[1:5]
sys.path.insert(0, package_root)

from tools.skills.ecosystem import sandbox as _sb

policy = json.loads(Path(policy_path).read_text(encoding="utf-8"))
_sb.install_import_gate(policy)
_sb.patch_socket(policy)
builtins_dict = _sb.restricted_builtins(policy, Path(workdir))
_exec_ref = exec
_builtins_module = sys.modules["builtins"]
for _name in ("exec", "eval", "compile"):
    _builtins_module.__dict__.pop(_name, None)
_builtins_module.__dict__.update(builtins_dict)

code = Path(code_path).read_text(encoding="utf-8")
mode = "exec"
# Intentional: this payload run happens only inside the sandboxed worker
# subprocess spawned via Popen in Sandbox.run — never in the parent
# process. Save-then-restrict: _exec_ref was captured before
# exec/eval/compile were removed from the builtins module, so the payload
# still runs, under restricted __builtins__, the import gate, the
# filesystem gate, the socket patch, and the Win32 Job Object limits.
_exec_ref(compile(code, str(code_path), mode), {"__name__": "__main__", "__builtins__": builtins_dict})
'''


def _cap_text(text: str | None, cap: int) -> str:
    if not text:
        return ""
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n...[truncated {len(text) - cap} chars]"


@dataclass(frozen=True)
class SandboxResult:
    """Outcome of one sandboxed run."""

    ok: bool
    output: str
    error: str | None = None
    timed_out: bool = False
    exit_code: int = 0


class Sandbox:
    """Run skill payloads in a policy-enforced worker subprocess.

    Policy enforcement only — NOT a trust boundary (pure-Python hooks
    are bypassable; the Win32 Job Object provides kernel-enforced
    memory/time limits).
    """

    def __init__(self, policy: dict | None = None) -> None:
        self.policy = dict(DEFAULT_POLICY)
        if policy is not None:
            self.policy.update(policy)
        validate_policy(self.policy)
        self._run_counter = 0

    def run(
        self,
        code: str,
        workdir: Path,
        policy: dict | None = None,
        timeout_ms: int | None = None,
    ) -> SandboxResult:
        """Execute `code` in a fresh worker process under the policy.

        `policy` overrides the sandbox default for this run (e.g. a
        per-skill policy granting the skill directory).
        """
        effective = policy or self.policy
        self._run_counter += 1
        run_id = self._run_counter
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
        run_dir = workdir / f".sandbox-run-{run_id}"
        run_dir.mkdir(exist_ok=True)
        policy_path = run_dir / "policy.json"
        code_path = run_dir / "payload.py"
        worker_path = run_dir / "worker.py"
        policy_path.write_text(json.dumps(effective, indent=2), encoding="utf-8")
        code_path.write_text(code, encoding="utf-8")
        worker_path.write_text(_WORKER_SOURCE, encoding="utf-8")

        package_root = Path(__file__).resolve().parents[3]
        resources = effective.get("resources", {})
        wall_ms = timeout_ms or resources.get("wall_time_ms", 30000)
        memory_mb = resources.get("memory_mb", 256)
        cap = effective.get("stdio", {}).get("cap", 65536)
        env = sanitized_env(effective.get("env_allowlist", []))
        creationflags = 0
        if os.name == "nt":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

        try:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    str(worker_path),
                    str(package_root),
                    str(policy_path),
                    str(code_path),
                    str(workdir),
                ],
                cwd=str(workdir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=creationflags,
            )
        except OSError as exc:
            return SandboxResult(ok=False, output="", error=f"spawn failed: {exc}", exit_code=-1)

        job_handle = None
        proc_handle = None
        if os.name == "nt":
            try:
                job_handle = _create_job_object(memory_mb, wall_ms)
                proc_handle = _open_process(proc.pid)
                _assign_process_to_job(job_handle, proc_handle)
            except OSError as exc:
                proc.kill()
                proc.wait()
                if proc_handle is not None:
                    _close_job(proc_handle)
                if job_handle is not None:
                    _close_job(job_handle)
                return SandboxResult(
                    ok=False, output="", error=f"job object failed: {exc}", exit_code=-1
                )

        try:
            try:
                stdout, stderr = proc.communicate(timeout=(wall_ms / 1000) + 2)
            except subprocess.TimeoutExpired:
                proc.kill()
                stdout, stderr = proc.communicate()
                return SandboxResult(
                    ok=False,
                    output=_cap_text(stdout, cap),
                    error=_cap_text(stderr, cap) or "timed out",
                    timed_out=True,
                    exit_code=proc.returncode or -1,
                )
        finally:
            if proc_handle is not None:
                _close_job(proc_handle)
            if job_handle is not None:
                _close_job(job_handle)

        if proc.returncode != 0:
            return SandboxResult(
                ok=False,
                output=_cap_text(stdout, cap),
                error=_cap_text(stderr, cap) or f"exit code {proc.returncode}",
                exit_code=proc.returncode,
            )
        return SandboxResult(
            ok=True,
            output=_cap_text(stdout, cap),
            error=_cap_text(stderr, cap) or None,
            exit_code=0,
        )