"""J5 Harness Domain System.

Domain-aware configuration, routing, and project management for
multi-domain harness operations (quant, finance, drone, research, coding, general).
"""

from __future__ import annotations

from .registry import (
    DomainRegistry,
    ProjectRegistry,
    DomainConfig,
    ProjectConfig,
    DomainModelConfig,
    DomainConstraints,
    get_domain_registry,
    get_project_registry,
    load_project_config,
    list_available_domains,
    list_projects,
)

from .router import (
    DomainAwareRouter,
    MultiProjectRouter,
    DomainRoutingDecision,
)

__all__ = [
    "DomainRegistry",
    "ProjectRegistry",
    "DomainConfig",
    "ProjectConfig",
    "DomainModelConfig",
    "DomainConstraints",
    "get_domain_registry",
    "get_project_registry",
    "load_project_config",
    "list_available_domains",
    "list_projects",
    "DomainAwareRouter",
    "MultiProjectRouter",
    "DomainRoutingDecision",
]

__version__ = "1.0.0"