"""CLI: pick <task_type> | health | status | scores. JSON output only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make `python tools/router/router_cli.py ...` work from the repo root
# as well as `python -m tools.router.router_cli`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    from tools.router.model_registry import TASK_TYPES, default_chain, validate_task_type
    from tools.router.health_probe import HealthTracker
    from tools.router.feedback_loop import FeedbackLoop
    from tools.router.fallback_chain import FallbackChainBuilder
    from tools.router.free_model_router import FreeModelRouter
    from tools.router.gateway_adapters import vpn_rotation_advisory
except ImportError:  # direct script fallback
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from model_registry import TASK_TYPES, default_chain, validate_task_type  # type: ignore
    from health_probe import HealthTracker  # type: ignore
    from feedback_loop import FeedbackLoop  # type: ignore
    from fallback_chain import FallbackChainBuilder  # type: ignore
    from free_model_router import FreeModelRouter  # type: ignore
    from gateway_adapters import vpn_rotation_advisory  # type: ignore


def _router() -> FreeModelRouter:
    tracker = HealthTracker()
    feedback = FeedbackLoop()
    chains = FallbackChainBuilder(tracker)
    return FreeModelRouter(tracker, feedback, chains)


def cmd_pick(task_type: str) -> dict:
    router = _router()
    decision = router.pick(validate_task_type(task_type))
    return {"ok": True, "task_type": task_type, **decision.to_dict()}


def cmd_health() -> dict:
    router = _router()
    snap = router.tracker.snapshot()
    return {"ok": True, "models": snap, "quarantined": router.tracker.quarantined_models()}


def cmd_status() -> dict:
    router = _router()
    chains = {t: [e.to_dict() for e in router.chains.build_chain(t, include_unavailable=True)]
              for t in TASK_TYPES}
    static = {t: default_chain(t) for t in TASK_TYPES}
    return {"ok": True, "router": router.status(), "chains": chains,
            "static_chains": static, "vpn_advisory": vpn_rotation_advisory()}


def cmd_scores() -> dict:
    router = _router()
    return {"ok": True, "scores": router.feedback.all_scores(),
            "degrading": router.feedback.degrading_models()}


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="router_cli", description="Free model router CLI (JSON output)")
    sub = p.add_subparsers(dest="command", required=True)
    pp = sub.add_parser("pick", help="pick a model for a task type")
    pp.add_argument("task_type", help=f"one of {list(TASK_TYPES)}")
    sub.add_parser("health", help="show per-model health")
    sub.add_parser("status", help="show router status + chains")
    sub.add_parser("scores", help="show EMA quality scores")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pick":
            result = cmd_pick(args.task_type)
        elif args.command == "health":
            result = cmd_health()
        elif args.command == "status":
            result = cmd_status()
        elif args.command == "scores":
            result = cmd_scores()
        else:
            result = {"ok": False, "error": f"unknown command {args.command!r}"}
    except (ValueError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
