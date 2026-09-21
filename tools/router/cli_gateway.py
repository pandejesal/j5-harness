"""Real dispatch backend: shell out to worker CLIs (opencode, kilo, prime).

This is the module that makes J5 prompts actually execute. The Zen HTTP
adapter posts to placeholder endpoints; this adapter runs the real CLIs
installed on the machine and captures their answers:

- opencode: ``opencode run "<prompt>" -m <provider/model> --dir <dir>
  --title <title> --format json`` — headless, exits on completion, emits
  a JSON event stream on stdout (``text`` parts carry the answer,
  ``step_finish`` carries token usage).
- (kilo / prime-agent transports plug in here behind the same interface.)

Implements :class:`GatewayInterface` from
:mod:`tools.router.gateway_adapters`, so health tracking, fallback chains,
circuit breakers, and the trust-but-verify ledger keep working unchanged —
they now observe real successes and failures instead of simulated ones.

Windows-safe: resolves real ``.exe`` binaries (never ``.ps1``/``.cmd``
shims, which ``CreateProcess`` cannot run directly), forces UTF-8 I/O,
and enforces a hard timeout so a stuck worker can never hang the harness.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

try:
    from tools.router.gateway_adapters import GatewayError, GatewayInterface
except ImportError:  # script-mode fallback
    from gateway_adapters import GatewayError, GatewayInterface  # type: ignore[no-redef]

# Harness model id -> CLI model id. The `opencode` provider prefix is the
# default; ids that already contain "/" pass through untouched. Entries here
# override the default for workers that live under a different provider.
MODEL_MAP: dict[str, str] = {
    # e.g. "laguna-s-2.1-free": "opencode-go/laguna-s-2.1-free",
}

DEFAULT_PROVIDER_PREFIX = "opencode"
DEFAULT_TIMEOUT_S = 600.0  # model turns can run several minutes
DEFAULT_TITLE_PREFIX = "j5"

_RATE_LIMIT_RE = re.compile(r"429|rate.?limit|retry-after|too many requests", re.IGNORECASE)
_AUTH_RE = re.compile(r"\b401\b|unauthorized|invalid api key|authentication", re.IGNORECASE)
_RETRY_AFTER_RE = re.compile(r"retry[^0-9]{0,12}(\d+)", re.IGNORECASE)


def find_opencode_binary() -> str | None:
    """Resolve a directly-executable opencode binary (never a .ps1 shim)."""
    candidates: list[str] = []
    seen: set[str] = set()

    # 1. npm global install layout: %APPDATA%\npm\node_modules\... .
    appdata = os.environ.get("APPDATA", "")
    userprofile = os.environ.get("USERPROFILE", "")
    roots = []
    if appdata:
        roots.append(os.path.join(appdata, "npm"))
    if userprofile:
        roots.append(os.path.join(userprofile, "AppData", "Roaming", "npm"))
    for base in roots:
        candidates.append(str(Path(base) / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"))

    # 2. Anything ending in opencode.exe on PATH.
    found = shutil.which("opencode.exe")
    if found:
        candidates.append(found)

    for cand in candidates:
        if cand and cand not in seen and Path(cand).is_file():
            seen.add(cand)
            return cand
    return None


def cli_model_id(model_id: str, prefix: str = DEFAULT_PROVIDER_PREFIX) -> str:
    """Map a harness model id to a CLI `-m provider/model` id."""
    if "/" in model_id:
        return model_id
    if model_id in MODEL_MAP:
        return MODEL_MAP[model_id]
    return f"{prefix}/{model_id}"


def extract_opencode_text(stdout: str) -> tuple[str, dict]:
    """Fold an `opencode run --format json` event stream into answer text.

    Returns (text, usage). Falls back to raw stdout when no JSON text
    events are present (e.g. default-format output).
    """
    chunks: list[str] = []
    usage: dict = {}
    session_id: str | None = None
    saw_json = False
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        saw_json = True
        if not isinstance(event, dict):
            continue
        session_id = session_id or event.get("sessionID")
        if event.get("type") == "text":
            part = event.get("part") or {}
            text = part.get("text")
            if isinstance(text, str):
                chunks.append(text)
        elif event.get("type") == "step_finish":
            part = event.get("part") or {}
            tokens = part.get("tokens") or {}
            usage = {
                "tokens_total": tokens.get("total"),
                "tokens_input": tokens.get("input"),
                "tokens_output": tokens.get("output"),
                "cost": tokens.get("cost", part.get("cost", 0)),
                "finish_reason": part.get("reason"),
            }
    text = "".join(chunks).strip()
    if session_id:
        usage["session_id"] = session_id
    if not text and not saw_json:
        text = stdout.strip()
    return text, usage


def classify_cli_failure(stderr: str, stdout: str) -> tuple[str, int | None, float | None]:
    """Map CLI failure output to (message, status_code, retry_after_s).

    429/401 codes feed the health tracker so quarantine and failover behave
    exactly like the HTTP adapter path.
    """
    blob = f"{stderr}\n{stdout}"
    tail = blob.strip()[-2000:]
    retry_after: float | None = None
    m = _RETRY_AFTER_RE.search(blob)
    if m:
        try:
            retry_after = float(m.group(1))
        except (TypeError, ValueError):
            retry_after = None
    if _RATE_LIMIT_RE.search(blob):
        return (f"worker rate-limited: {tail}", 429, retry_after)
    if _AUTH_RE.search(blob):
        return (f"worker auth failure: {tail}", 401, None)
    return (f"worker failed: {tail}", None, None)


class OpencodeCliAdapter(GatewayInterface):
    """Dispatch prompts via `opencode run` subprocesses.

    One in-flight dispatch by default (shared free-tier IP bucket), same
    contract as :class:`ZenGatewayAdapter.send`: returns a response dict
    with an ``output`` key (picked up by ``_extract_text``), raises
    :class:`GatewayError` on failure.
    """

    def __init__(
        self,
        binary: str | None = None,
        workdir: str | Path | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_in_flight: int = 1,
        provider_prefix: str = DEFAULT_PROVIDER_PREFIX,
        extra_args: list[str] | None = None,
    ) -> None:
        resolved = binary or find_opencode_binary()
        if not resolved:
            raise ValueError(
                "opencode binary not found (checked npm global install and PATH). "
                "Install opencode or set J5_GATEWAY=zen to use the HTTP adapter."
            )
        self.binary = resolved
        self.workdir = Path(workdir) if workdir else Path(tempfile.gettempdir()) / "j5-worker"
        self.timeout_s = timeout_s
        self.max_in_flight = max(1, max_in_flight)
        self.provider_prefix = provider_prefix
        self.extra_args = list(extra_args or [])
        self._lock = threading.Lock()
        self._alock = asyncio.Lock()
        self._in_flight = 0

    def _resolve_cwd(self, workdir: str | Path | None) -> Path:
        if workdir and Path(workdir).is_dir():
            return Path(workdir)
        self.workdir.mkdir(parents=True, exist_ok=True)
        return self.workdir

    def send(
        self,
        model: str,
        prompt: str,
        timeout_s: float | None = None,
        *,
        workdir: str | Path | None = None,
        task_id: str | None = None,
    ) -> dict:
        """Run one headless `opencode run` and return its answer.

        Extra keyword args (``workdir``, ``task_id``) are accepted so the
        harness router can pass per-project context; the Zen adapter ignores
        them via its own tolerant signature.
        """
        timeout = timeout_s or self.timeout_s
        cli_model = cli_model_id(model, self.provider_prefix)
        cwd = self._resolve_cwd(workdir)
        title = f"{DEFAULT_TITLE_PREFIX}-{task_id}" if task_id else DEFAULT_TITLE_PREFIX
        cmd = [
            self.binary, "run", prompt,
            "-m", cli_model,
            "--dir", str(cwd),
            "--title", title,
            "--format", "json",
            *self.extra_args,
        ]
        env = {
            **os.environ,
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "NO_COLOR": "1",
        }
        try:
            # stdin=DEVNULL: headless dispatch must NEVER block on an
            # interactive permission prompt. A denied tool becomes a
            # GatewayError, which the fallback chain handles gracefully.
            proc = subprocess.run(
                cmd,
                cwd=str(cwd),
                capture_output=True,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=env,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GatewayError(f"opencode run timed out after {timeout:.0f}s (model {cli_model})") from exc
        except OSError as exc:
            raise GatewayError(f"opencode launch failed: {exc}") from exc

        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
        text, usage = extract_opencode_text(stdout)
        if text:
            return {
                "output": text,
                "usage": usage,
                "model": cli_model,
                "exit_code": proc.returncode,
            }
        message, status, retry_after = classify_cli_failure(stderr, stdout)
        raise GatewayError(message, status_code=status, retry_after_s=retry_after)

    async def asend(self, model: str, prompt: str) -> dict:
        async with self._alock:
            with self._lock:
                if self._in_flight >= self.max_in_flight:
                    raise GatewayError("dispatch serialized: gateway busy")
                self._in_flight += 1
            try:
                return await asyncio.to_thread(self.send, model, prompt)
            finally:
                with self._lock:
                    self._in_flight -= 1


__all__ = [
    "MODEL_MAP",
    "DEFAULT_PROVIDER_PREFIX",
    "DEFAULT_TIMEOUT_S",
    "find_opencode_binary",
    "cli_model_id",
    "extract_opencode_text",
    "classify_cli_failure",
    "OpencodeCliAdapter",
]
