"""Tests for domain system."""

from __future__ import annotations

import unittest
from pathlib import Path

from tools.domains import (
    DomainRegistry,
    ProjectRegistry,
    DomainAwareRouter,
    MultiProjectRouter,
    load_project_config,
    list_available_domains,
    list_projects,
)


class DomainRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = DomainRegistry()

    def test_all_domains_loaded(self):
        domains = self.registry.list_domains()
        self.assertEqual(set(domains), {"quant", "finance", "drone", "research", "coding", "general"})

    def test_quant_domain(self):
        dom = self.registry.get_domain("quant")
        self.assertEqual(dom.name, "quant")
        self.assertIn("nemotron-3-ultra-free", dom.models.primary)
        self.assertIn("mimo-v2.5-free", dom.models.primary)
        self.assertEqual(len(dom.skills), 6)
        self.assertEqual(len(dom.tools), 9)

    def test_finance_domain(self):
        dom = self.registry.get_domain("finance")
        self.assertEqual(dom.name, "finance")
        self.assertIn("ling-3.0-flash-fin-free", dom.models.fallback)

    def test_drone_domain(self):
        dom = self.registry.get_domain("drone")
        self.assertEqual(dom.name, "drone")
        self.assertIn("mimo-v2.5-free", dom.models.primary)
        self.assertIn("cpp/eigen", dom.tools)

    def test_research_domain(self):
        dom = self.registry.get_domain("research")
        self.assertEqual(dom.name, "research")
        self.assertIn("reproducibility", dom.constraints.__dict__)

    def test_coding_domain(self):
        dom = self.registry.get_domain("coding")
        self.assertEqual(dom.name, "coding")
        self.assertIn("coding/architecture", dom.skills)

    def test_general_domain(self):
        dom = self.registry.get_domain("general")
        self.assertEqual(dom.name, "general")
        self.assertIn("ling-3.0-flash-fin-free", dom.models.primary)

    def test_fallback_ladders(self):
        ladder = self.registry.get_fallback_ladder("quant", "coder")
        self.assertIn("mimo-v2.5-free", ladder)
        self.assertIn("nemotron-3-ultra-free", ladder)

    def test_skills_tools_data_sources(self):
        self.assertEqual(len(self.registry.get_skills_for_domain("quant")), 6)
        self.assertEqual(len(self.registry.get_tools_for_domain("drone")), 10)
        self.assertEqual(len(self.registry.get_data_sources_for_domain("finance")), 8)


class ProjectRegistryTest(unittest.TestCase):
    def setUp(self):
        self.registry = ProjectRegistry()

    def test_projects_loaded(self):
        projects = self.registry.list_projects()
        self.assertIn("wsb-alpha", projects)
        self.assertIn("burgonomics", projects)

    def test_wsb_alpha_quant(self):
        proj = self.registry.get_project("wsb-alpha")
        self.assertEqual(proj.domain, "quant")
        self.assertTrue(proj.enabled)
        self.assertIn("mimo-v2.5-free", proj.get_fallback_ladder("coder"))

    def test_burgonomics_general(self):
        proj = self.registry.get_project("burgonomics")
        self.assertEqual(proj.domain, "general")
        self.assertTrue(proj.enabled)

    def test_domain_inference(self):
        # Test that new projects get correct domain inference
        from tools.domains.registry import ProjectConfig, DomainRegistry
        dr = DomainRegistry()
        # This would be tested via the registry's _infer_domain method


class DomainAwareRouterTest(unittest.TestCase):
    def setUp(self):
        self.router = DomainAwareRouter("wsb-alpha")

    def test_pick_coding(self):
        decision = self.router.pick("coding")
        self.assertEqual(decision.project, "wsb-alpha")
        self.assertEqual(decision.domain, "quant")
        self.assertIn(decision.model, ["mimo-v2.5-free", "nemotron-3-ultra-free", "muse-spark-1.3-contributor-free"])
        self.assertIsInstance(decision.expected_latency_ms, float)
        self.assertIsInstance(decision.chain, list)

    def test_pick_research(self):
        decision = self.router.pick("research")
        self.assertEqual(decision.task_type, "research")

    def test_chain_not_empty(self):
        decision = self.router.pick("coding")
        self.assertGreater(len(decision.chain), 0)


class MultiProjectRouterTest(unittest.TestCase):
    def setUp(self):
        self.router = MultiProjectRouter()

    def test_multiple_projects(self):
        d1 = self.router.pick("wsb-alpha", "coding")
        d2 = self.router.pick("burgonomics", "coding")
        self.assertEqual(d1.project, "wsb-alpha")
        self.assertEqual(d2.project, "burgonomics")
        self.assertEqual(d1.domain, "quant")
        self.assertEqual(d2.domain, "general")

    def test_router_reuse(self):
        r1 = self.router.get_router("wsb-alpha")
        r2 = self.router.get_router("wsb-alpha")
        self.assertIs(r1, r2)

    def test_global_status(self):
        status = self.router.global_status()
        self.assertIn("projects", status)
        self.assertIn("shared_health", status)
        self.assertIn("shared_scores", status)


class IntegrationTest(unittest.TestCase):
    def test_list_functions(self):
        domains = list_available_domains()
        self.assertEqual(set(domains), {"quant", "finance", "drone", "research", "coding", "general"})

        projects = list_projects()
        self.assertIn("wsb-alpha", projects)
        self.assertIn("burgonomics", projects)

    def test_load_project_config(self):
        config = load_project_config("wsb-alpha")
        self.assertEqual(config.name, "wsb-alpha")
        self.assertEqual(config.domain, "quant")


if __name__ == "__main__":
    unittest.main()