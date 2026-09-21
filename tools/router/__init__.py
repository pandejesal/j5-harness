"""Superior free model router.

Stdlib-only Python 3.12 package for routing tasks across free-tier
Zen-gateway models with health tracking, fallback chains, and a
response feedback loop.

Shared Zen free-tier key is bucketed per IP; VPN rotation is
advisory-only (see gateway_adapters.vpn_rotation_advisory).
Dispatch is serialized (1 in-flight by default).
"""

from __future__ import annotations

from .free_model_router import FreeModelRouter, RoutingDecision
from .health_probe import HealthTracker
from .feedback_loop import FeedbackLoop
from .fallback_chain import FallbackChainBuilder, ChainEntry
from .model_registry import MODELS, validate_task_type, default_chain
from .gateway_adapters import ZenGatewayAdapter, GatewayError, vpn_rotation_advisory
from .router_cli import main as router_cli_main

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "FreeModelRouter",
    "RoutingDecision",
    "HealthTracker",
    "FeedbackLoop",
    "FallbackChainBuilder",
    "ChainEntry",
    "MODELS",
    "validate_task_type",
    "default_chain",
    "ZenGatewayAdapter",
    "GatewayError",
    "vpn_rotation_advisory",
    "router_cli_main",
]