#!/usr/bin/env python3
"""
Antigravity Bridge for J5 Harness — Kilo/Antigravity Integration.

This script bridges J5 Harness with Google Antigravity for Kilo probe round-trips.
It accepts a prompt file, executes the task via Antigravity, and returns structured JSON.

Usage:
    python antigravity_bridge.py --prompt-file <file> --cwd <dir> --print --output-format json --print-timeout <seconds> --json

Output JSON format:
    {
        "status": "success" | "error",
        "output": "model response text",
        "evidence": "optional evidence text",
        "error": "error message if status=error"
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

try:
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig
    ANTIGRAVITY_SDK_AVAILABLE = True
except ImportError:
    ANTIGRAVITY_SDK_AVAILABLE = False

# Internal hard timeout ceiling (seconds) — CLI path only.
# --print-timeout may be lower; the subprocess timeout is print_timeout + 30.
_DEFAULT_PRINT_TIMEOUT = 120


async def run_antigravity_task(
    prompt: str,
    working_dir: str | None = None,
    system_prompt: str | None = None,
    effort: str | None = None,
    mode: str | None = None,
    sandbox: str | None = None,
    print_timeout: int = _DEFAULT_PRINT_TIMEOUT,
    print_mode: bool = False,
    output_format: str | None = None,
    add_dirs: list[str] | None = None,
) -> dict:
    """
    Executes a task in Antigravity and captures the output.

    Hardened:
    - No shell=True (arg-list subprocess invocation).
    - No unconditional os.chdir (SDK path uses cwd save/restore; CLI path
      passes cwd= kwarg and --add-dir).
    - Mandatory --print --output-format json for structured output.
    - Internal hard timeout on subprocess.
    - JSON stdout parsing with stderr captured as evidence.
    """
    sys_instruction = system_prompt or (
        "You are Google Antigravity, pair-programming with Hermes Agent. "
        "Complete the requested task thoroughly, including file edits, terminal commands, "
        "and verification. Return a concise, structured summary of actions taken and final results."
    )

    if ANTIGRAVITY_SDK_AVAILABLE:
        config = LocalAgentConfig(
            system_instructions=sys_instruction,
            capabilities=CapabilitiesConfig(),
        )

        output_tokens = []
        # Save and restore cwd to avoid process-global side effect.
        original_cwd = os.getcwd()
        try:
            if working_dir:
                os.chdir(working_dir)
            async with Agent(config) as agent:
                response = await agent.chat(prompt)
                async for token in response:
                    output_tokens.append(token)
                    sys.stdout.write(token)
                    sys.stdout.flush()
                print()

                full_text = "".join(output_tokens)
                return {"status": "success", "output": full_text}
        except Exception as e:
            return {"status": "error", "error": str(e)}
        finally:
            os.chdir(original_cwd)
    else:
        # Fallback to agy CLI — arg-list invocation, never shell=True.
        import subprocess as _sp
        try:
            cmd = ["agy"]
            if print_mode:
                cmd.extend(["--print", prompt])
            else:
                cmd.append(prompt)
            if output_format:
                cmd.extend(["--output-format", output_format])
            if add_dirs:
                for d in add_dirs:
                    cmd.extend(["--add-dir", d])
            elif working_dir:
                cmd.extend(["--add-dir", working_dir])
            cmd.extend(["--print-timeout", f"{print_timeout}s"])
            if effort:
                cmd.extend(["--effort", effort])
            if mode:
                cmd.extend(["--mode", mode])
            if sandbox:
                cmd.extend(["--sandbox", sandbox])

            proc = _sp.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=working_dir or os.getcwd(),
                shell=False,
                timeout=print_timeout + 30,
            )
            retry_after: float | None = None
            if isinstance(proc, _sp.CompletedProcess):
                raw = proc.stderr.strip()
                try:
                    retry_after = float(raw) if raw else None
                except (TypeError, ValueError):
                    retry_after = None
                raise _sp.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
            raise _sp.CalledProcessError(proc.returncode, cmd, proc.stdout, proc.stderr)
        except _sp.TimeoutExpired as exc:  # type: ignore[attr-defined]
            retry_after: float | None = None
            if isinstance(exc, _sp.TimeoutExpired):
                raw = exc.stderr.strip() if exc.stderr else None
                try:
                    retry_after = float(raw) if raw else None
                except (TypeError, ValueError):
                    retry_after = None
                raise _sp.CalledProcessError(exc.returncode, exc.cmd, exc.stdout, exc.stderr) from exc
            raise _sp.CalledProcessError(exc.returncode, exc.cmd, exc.stdout, exc.stderr) from exc
        except _sp.CalledProcessError as exc:  # type: ignore[attr-defined]
            retry_after: float | None = None
            if isinstance(exc, _sp.CalledProcessError):
                raw = exc.stderr.strip() if exc.stderr else None
                try:
                    retry_after = float(raw) if raw else None
                except (TypeError, ValueError):
                    retry_after = None
                raise GatewayError(f"zen http {exc.returncode} at {endpoint}",
                                   status_code=exc.returncode,
                                   retry_after_s=retry_after) from exc
            raise GatewayError(str(exc)) from exc
        except OSError as exc:
            raise GatewayError(f"zen transport error at {endpoint}: {exc}") from exc

        # Try to parse JSON output from agy
        stdout_text = proc.stdout.strip()
        try:
            result_data = json.loads(stdout_text) if stdout_text else {}
            output = result_data.get("output", stdout_text)
        except (json.JSONDecodeError, ValueError):
            output = stdout_text

        evidence = {
            "stdout_preview": stdout_text[:500],
            "stderr_preview": proc.stderr.strip()[:500],
            "returncode": proc.returncode,
        }

        if proc.returncode == 0:
            return {"status": "success", "output": output, "evidence": evidence}
        else:
            return {
                "status": "error",
                "error": stderr_text or output,
                "evidence": evidence,
            }


def main():
    parser = argparse.ArgumentParser(description="Antigravity Bridge for J5 Harness")
    parser.add_argument("prompt", nargs="?", help="The prompt/task to delegate to Antigravity")
    parser.add_argument("--prompt-file", "-f", help="Path to a text file containing the prompt")
    parser.add_argument("--cwd", "-d", help="Working directory for Antigravity to operate in", default=None)
    parser.add_argument("--system-prompt", "-s", help="Custom system instructions for Antigravity", default=None)
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    # New hardened flags — all optional, backward-compatible.
    parser.add_argument("--effort", "-e", help="Aggy effort level (e.g. low, medium, high)", default=None)
    parser.add_argument("--mode", "-m", help="Aggy execution mode", default=None)
    parser.add_argument("--sandbox", help="Aggy sandbox policy", default=None)
    parser.add_argument("--print", action="store_true", help="Enable print mode (required for --output-format)")
    parser.add_argument("--output-format", choices=["json", "text", "stream-json"], default=None, help="Output format for print mode")
    parser.add_argument("--add-dir", action="append", help="Additional directories to include (passed to agy --add-dir)")
    parser.add_argument(
        "--print-timeout", "-t",
        type=int,
        default=_DEFAULT_PRINT_TIMEOUT,
        help=f"Seconds before agy --print times out (default: {_DEFAULT_PRINT_TIMEOUT})",
    )

    args = parser.parse_args()

    prompt_text = ""
    if args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as fp:
            prompt_text = fp.read()
    elif args.prompt:
        prompt_text = args.prompt
    elif not sys.stdin.isatty():
        prompt_text = sys.stdin.read()
    else:
        parser.print_help()
        sys.exit(1)

    result = asyncio.run(run_antigravity_task(
        prompt=prompt_text,
        working_dir=args.cwd,
        system_prompt=args.system_prompt,
        effort=args.effort,
        mode=args.mode,
        sandbox=args.sandbox,
        print_timeout=args.print_timeout,
        print_mode=args.print,
        output_format=args.output_format,
        add_dirs=args.add_dir,
    ))

    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("status") == "error":
        print(f"\n[Antigravity Error]: {result.get('error')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()