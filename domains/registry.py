"""Domain configuration loader and registry for J5 Harness.

Loads domain-specific configurations, merges with project overrides,
and provides domain-aware model routing, skill loading, and tool access.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from tools.harness.integration import load_config as load_reliability_config


@dataclass(frozen=True)
class DomainModelConfig:
    """Model configuration for a domain."""
    primary: list[str]
    fallback: list[str]


@dataclass(frozen=True)
class DomainConstraints:
    """Operational constraints for a domain."""
    latency_critical: bool = False
    deterministic_execution: bool = False
    audit_trail: bool = False
    regulatory_compliance: list[str] = field(default_factory=list)
    real_time: bool = False
    safety_critical: bool = False
    hardware_in_loop: bool = False
    reproducibility: bool = False
    citation_tracking: bool = False
    peer_review_ready: bool = False
    open_science: bool = False
    code_quality: bool = False
    test_coverage: bool = False
    security: bool = False
    maintainability: bool = False
    data_privacy: bool = False
    helpful: bool = False
    harmless: bool = False
    honest: bool = False


@dataclass(frozen=True)
class DomainConfig:
    """Complete domain configuration."""
    name: str
    description: str
    models: DomainModelConfig
    skills: list[str]
    tools: list[str]
    data_sources: list[str]
    constraints: DomainConstraints
    fallback_ladders: dict[str, list[str]]


class DomainRegistry:
    """Registry of domain configurations with project-specific overrides."""

    def __init__(self, domains_config_path: str | Path | None = None) -> None:
        self.config_path = Path(domains_config_path) if domains_config_path else (
            Path(__file__).resolve().parent / "domains.config.json"
        )
        self._domains: dict[str, DomainConfig] = {}
        self._project_overrides: dict[str, dict] = {}
        self._load_domains()

    def _load_domains(self) -> None:
        """Load domain configurations from JSON file."""
        with self.config_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        for name, domain_data in data.get("domains", {}).items():
            models = DomainModelConfig(
                primary=domain_data["models"]["primary"],
                fallback=domain_data["models"]["fallback"]
            )
            constraints = DomainConstraints(**domain_data.get("constraints", {}))
            self._domains[name] = DomainConfig(
                name=name,
                description=domain_data["description"],
                models=models,
                skills=domain_data["skills"],
                tools=domain_data["tools"],
                data_sources=domain_data["data_sources"],
                constraints=constraints,
                fallback_ladders=domain_data["fallbackLadders"]
            )

    def get_domain(self, name: str) -> DomainConfig:
        """Get domain configuration by name."""
        if name not in self._domains:
            raise ValueError(f"Unknown domain: {name}. Available: {list(self._domains.keys())}")
        return self._domains[name]

    def list_domains(self) -> list[str]:
        """List all available domain names."""
        return list(self._domains.keys())

    def get_models_for_domain(self, domain: str) -> list[str]:
        """Get all models (primary + fallback) for a domain."""
        d = self.get_domain(domain)
        return d.models.primary + d.models.fallback

    def get_fallback_ladder(self, domain: str, role: str) -> list[str]:
        """Get fallback ladder for a domain and role."""
        d = self.get_domain(domain)
        return d.fallback_ladders.get(role, d.fallback_ladders.get("coder", []))

    def get_skills_for_domain(self, domain: str) -> list[str]:
        """Get skills for a domain."""
        return self.get_domain(domain).skills

    def get_tools_for_domain(self, domain: str) -> list[str]:
        """Get tools for a domain."""
        return self.get_domain(domain).tools

    def get_data_sources_for_domain(self, domain: str) -> list[str]:
        """Get data sources for a domain."""
        return self.get_domain(domain).data_sources

    def get_constraints_for_domain(self, domain: str) -> DomainConstraints:
        """Get constraints for a domain."""
        return self.get_domain(domain).constraints


@dataclass(frozen=True)
class ProjectConfig:
    """Project-specific configuration merging domain defaults with overrides."""
    name: str
    domain: str
    domain_config: DomainConfig
    enabled: bool = True
    project_dir: str = ""
    custom_fallback_ladders: dict[str, list[str]] = field(default_factory=dict)
    custom_skills: list[str] = field(default_factory=list)
    custom_tools: list[str] = field(default_factory=list)
    custom_constraints: dict = field(default_factory=dict)
    env_vars: dict[str, str] = field(default_factory=dict)

    def get_fallback_ladder(self, role: str) -> list[str]:
        """Get fallback ladder with project overrides."""
        if role in self.custom_fallback_ladders:
            return self.custom_fallback_ladders[role]
        return self.domain_config.fallback_ladders.get(role, [])

    def get_all_skills(self) -> list[str]:
        """Get all skills (domain + custom)."""
        skills = set(self.domain_config.skills)
        skills.update(self.custom_skills)
        return list(skills)

    def get_all_tools(self) -> list[str]:
        """Get all tools (domain + custom)."""
        tools = set(self.domain_config.tools)
        tools.update(self.custom_tools)
        return list(tools)

    def get_constraints(self) -> DomainConstraints:
        """Get constraints with project overrides."""
        base = self.domain_config.constraints
        overrides = self.custom_constraints
        return DomainConstraints(
            latency_critical=overrides.get("latency_critical", base.latency_critical),
            deterministic_execution=overrides.get("deterministic_execution", base.deterministic_execution),
            audit_trail=overrides.get("audit_trail", base.audit_trail),
            regulatory_compliance=overrides.get("regulatory_compliance", base.regulatory_compliance),
            real_time=overrides.get("real_time", base.real_time),
            safety_critical=overrides.get("safety_critical", base.safety_critical),
            hardware_in_loop=overrides.get("hardware_in_loop", base.hardware_in_loop),
            reproducibility=overrides.get("reproducibility", base.reproducibility),
            citation_tracking=overrides.get("citation_tracking", base.citation_tracking),
            peer_review_ready=overrides.get("peer_review_ready", base.peer_review_ready),
            open_science=overrides.get("open_science", base.open_science),
            code_quality=overrides.get("code_quality", base.code_quality),
            test_coverage=overrides.get("test_coverage", base.test_coverage),
            security=overrides.get("security", base.security),
            maintainability=overrides.get("maintainability", base.maintainability),
            data_privacy=overrides.get("data_privacy", base.data_privacy),
            helpful=overrides.get("helpful", base.helpful),
            harmless=overrides.get("harmless", base.harmless),
            honest=overrides.get("honest", base.honest),
        )


class ProjectRegistry:
    """Registry of project configurations with domain awareness."""

    def __init__(self, domain_registry: DomainRegistry | None = None) -> None:
        self.domain_registry = domain_registry or DomainRegistry()
        self._projects: dict[str, ProjectConfig] = {}
        self._load_from_reliability_config()

    def _load_from_reliability_config(self) -> None:
        """Load projects from reliability.config.json."""
        try:
            reliability = load_reliability_config()
            projects = reliability.get("projects", {})
            dirs = reliability.get("dirs", {})
            fallback_ladders = reliability.get("fallbackLadders", {})

            for name, proj_config in projects.items():
                if not proj_config.get("enabled", False):
                    continue

                # Determine domain from project name or config
                domain = self._infer_domain(name, proj_config)
                domain_config = self.domain_registry.get_domain(domain)

                project_dir = dirs.get(name, "")
                custom_ladders = {}
                for role, ladder in fallback_ladders.items():
                    if role in ["coder", "planner", "bulk", "research"]:
                        custom_ladders[role] = ladder

                self._projects[name] = ProjectConfig(
                    name=name,
                    domain=domain,
                    domain_config=domain_config,
                    enabled=proj_config.get("enabled", True),
                    project_dir=project_dir,
                    custom_fallback_ladders=custom_ladders,
                )
        except Exception:
            pass  # Config optional

    def _infer_domain(self, name: str, config: dict) -> str:
        """Infer domain from project name or config."""
        name_lower = name.lower()
        if "quant" in name_lower or "trading" in name_lower or "alpha" in name_lower:
            return "quant"
        if "finance" in name_lower or "bank" in name_lower or "fund" in name_lower:
            return "finance"
        if "drone" in name_lower or "robot" in name_lower or "uav" in name_lower:
            return "drone"
        if "research" in name_lower or "science" in name_lower or "academic" in name_lower:
            return "research"
        if "code" in name_lower or "dev" in name_lower or "engineering" in name_lower:
            return "coding"
        return "general"

    def register_project(self, config: ProjectConfig) -> None:
        """Register a project configuration."""
        self._projects[config.name] = config

    def get_project(self, name: str) -> ProjectConfig:
        """Get project configuration by name."""
        if name not in self._projects:
            raise ValueError(f"Unknown project: {name}. Available: {list(self._projects.keys())}")
        return self._projects[name]

    def list_projects(self) -> list[str]:
        """List all registered project names."""
        return list(self._projects.keys())

    def get_enabled_projects(self) -> list[ProjectConfig]:
        """Get all enabled project configurations."""
        return [p for p in self._projects.values() if p.enabled]

    def get_projects_by_domain(self, domain: str) -> list[ProjectConfig]:
        """Get all projects for a specific domain."""
        return [p for p in self._projects.values() if p.domain == domain and p.enabled]


# Global registries
_domain_registry: DomainRegistry | None = None
_project_registry: ProjectRegistry | None = None


def get_domain_registry() -> DomainRegistry:
    """Get global domain registry (singleton)."""
    global _domain_registry
    if _domain_registry is None:
        _domain_registry = DomainRegistry()
    return _domain_registry


def get_project_registry() -> ProjectRegistry:
    """Get global project registry (singleton)."""
    global _project_registry
    if _project_registry is None:
        _project_registry = ProjectRegistry(get_domain_registry())
    return _project_registry


def load_project_config(project_name: str) -> ProjectConfig:
    """Load project configuration by name."""
    return get_project_registry().get_project(project_name)


def list_available_domains() -> list[str]:
    """List all available domains."""
    return get_domain_registry().list_domains()


def list_projects() -> list[str]:
    """List all registered projects."""
    return get_project_registry().list_projects()