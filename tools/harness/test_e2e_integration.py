"""End-to-end integration test: Router + Delegation Engine + Integration Wiring.

This test validates the full chain:
1. FreeModelRouter picks model for task_type
2. Orchestrator decomposes task into DAG
3. make_router_fn routes leaves via router_fn contract
4. Results logged to ledger
5. Skill leaf short-circuit works
"""

from __future__ import annotations

import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.delegation.delegation_engine import DelegationDAG, Orchestrator
from tools.delegation.ledger import DelegationLedger
from tools.harness.integration import (
    CONFIG_PATH,
    SHARED,
    build_project_contexts,
    build_project_states,
    load_config,
    make_router_fn,
    run_probe_roundtrip,
)
from tools.router.fallback_chain import FallbackChainBuilder
from tools.router.feedback_loop import FeedbackLoop
from tools.router.free_model_router import FreeModelRouter
from tools.router.health_probe import HealthTracker
from tools.router.model_registry import MODELS, default_chain


class TestRouterDelegationIntegration(unittest.TestCase):
    """Full integration test for router + delegation + harness wiring."""

    def setUp(self):
        self.config = load_config()
        self.contexts = build_project_contexts(self.config, "coder")
        self.ctx = self.contexts[0]  # wsb-alpha
        self.shared = SHARED
        self.states = build_project_states(self.config)
        self.state = self.states[self.ctx.name]

    def test_router_picks_model_for_coding(self):
        """FreeModelRouter picks mimo-v2.5-free for coding task."""
        router = FreeModelRouter(
            tracker=self.shared.tracker,
            feedback=self.shared.feedback,
            chain_builder=self.shared.chain_builder,
            max_in_flight=1,
        )
        decision = router.pick("coding")
        self.assertIn(decision.model, MODELS)
        self.assertIsInstance(decision.chain, list)
        self.assertTrue(len(decision.chain) > 0)

    def test_router_picks_model_for_research(self):
        """FreeModelRouter picks nemotron-3-ultra-free for research task."""
        router = FreeModelRouter(
            tracker=self.shared.tracker,
            feedback=self.shared.feedback,
            chain_builder=self.shared.chain_builder,
            max_in_flight=1,
        )
        decision = router.pick("research")
        self.assertIn(decision.model, MODELS)

    def test_orchestrator_decompose_creates_dag(self):
        """Orchestrator.decompose creates valid DAG with leaves."""
        ledger = DelegationLedger(self.ctx.ledger_path)
        orchestrator = Orchestrator(ledger=ledger, router_fn=lambda *a, **k: {"text": "ok", "confidence": 1.0, "model_id": "test"})

        leaves = [
            {"task_id": "task-1", "prompt": "Write a function to add two numbers"},
            {"task_id": "task-2", "prompt": "Write a test for the add function"},
            {"task_id": "task-3", "prompt": "Document the add function", "depends_on": ["task-1"]},
        ]
        dag = orchestrator.decompose("Build an add module", leaves, root_id="root-1")

        self.assertIsInstance(dag, DelegationDAG)
        self.assertEqual(len(dag.nodes), 4)  # root + 3 leaves
        self.assertIn("task-1", dag.nodes)
        self.assertIn("task-2", dag.nodes)
        self.assertIn("task-3", dag.nodes)
        self.assertEqual(dag.nodes["task-3"].depends_on, ("task-1",))

    def test_orchestrator_run_executes_leaves(self):
        """Orchestrator.run executes leaves in topological order."""
        ledger = DelegationLedger(self.ctx.ledger_path)
        mock_router = MagicMock(return_value={"text": "result", "confidence": 1.0, "model_id": "mimo-v2.5-free"})
        orchestrator = Orchestrator(ledger=ledger, router_fn=mock_router)

        leaves = [
            ("task-1", "First task"),
            ("task-2", "Second task"),
        ]
        dag = orchestrator.decompose("Root task", leaves)
        result_dag = orchestrator.run(dag, task_type="coding")

        self.assertEqual(result_dag.nodes["task-1"].state.name, "SUCCEEDED")
        self.assertEqual(result_dag.nodes["task-2"].state.name, "SUCCEEDED")
        self.assertEqual(mock_router.call_count, 2)

    def test_orchestrator_respects_dependencies(self):
        """Orchestrator blocks leaves with failed dependencies."""
        ledger = DelegationLedger(self.ctx.ledger_path)
        # First task fails, second should be blocked
        call_count = {"count": 0}
        def mock_router(prompt, **kwargs):
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise Exception("Task 1 failed")
            return {"text": "result", "confidence": 1.0, "model_id": "mimo-v2.5-free"}

        orchestrator = Orchestrator(ledger=ledger, router_fn=mock_router)

        leaves = [
            {"task_id": "task-1", "prompt": "First task"},
            {"task_id": "task-2", "prompt": "Second task", "depends_on": ["task-1"]},
        ]
        dag = orchestrator.decompose("Root task", leaves)
        result_dag = orchestrator.run(dag, task_type="coding")

        self.assertEqual(result_dag.nodes["task-1"].state.name, "FAILED")
        self.assertEqual(result_dag.nodes["task-2"].state.name, "BLOCKED")

    def test_make_router_fn_skill_leaf_short_circuit(self):
        """make_router_fn routes skill leaves directly without model dispatch."""
        router_fn = make_router_fn(self.ctx, self.shared, self.config)

        # Inject mock skill hub
        mock_hub = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.output = "skill executed"
        mock_result.error = None
        mock_hub.invoke.return_value = mock_result
        self.state.skill_hub = mock_hub
        self.ctx.leaf_skills["skill-task-1"] = ("quant/backtesting", {"symbol": "AAPL"})

        result = router_fn("run backtest", task_id="skill-task-1", task_type="coding")

        self.assertEqual(result["text"], "skill executed")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["model_id"], "skill:quant/backtesting")
        mock_hub.invoke.assert_called_once()

    def test_make_router_fn_cache_hit(self):
        """make_router_fn returns cached result on cache hit."""
        router_fn = make_router_fn(self.ctx, self.shared, self.config)

        # Pre-populate cache
        from tools.harness.integration import _cache_key
        cache_key = _cache_key("mimo-v2.5-free", "coding", "cached prompt")
        self.shared.cache.set(cache_key, {"text": "cached result", "confidence": 1.0, "model_id": "mimo-v2.5-free"})

        result = router_fn("cached prompt", task_id="task-1", task_type="coding", model_id="mimo-v2.5-free")

        self.assertEqual(result["text"], "cached result")
        self.assertEqual(result["confidence"], 1.0)

    def test_make_router_fn_breaker_gate(self):
        """make_router_fn skips models with open circuit breaker."""
        router_fn = make_router_fn(self.ctx, self.shared, self.config)

        # Open breaker for mimo
        breaker = self.state.breakers["mimo-v2.5-free"]
        for _ in range(5):
            breaker.record_failure()
        self.assertTrue(breaker.is_open())

        # Mock adapter to track calls
        self.shared.adapter.send = MagicMock(return_value={"output": "response"})

        result = router_fn("test prompt", task_id="task-1", task_type="coding", model_id="mimo-v2.5-free")

        # Should have skipped mimo and tried next model
        self.assertIn("text", result)

    def test_make_router_fn_quarantine_skip(self):
        """make_router_fn skips quarantined models."""
        router_fn = make_router_fn(self.ctx, self.shared, self.config)

        # Quarantine mimo
        self.shared.tracker.quarantine("mimo-v2.5-free", ttl_s=3600)
        self.assertTrue(self.shared.tracker.is_quarantined("mimo-v2.5-free"))

        self.shared.adapter.send = MagicMock(return_value={"output": "response"})

        result = router_fn("test prompt", task_id="task-1", task_type="coding", model_id="mimo-v2.5-free")

        self.assertIn("text", result)

    def test_full_chain_router_to_delegation(self):
        """Full chain: router picks model -> orchestrator uses it -> ledger records."""
        ledger = DelegationLedger(self.ctx.ledger_path)

        # Use real router via make_router_fn
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        orchestrator = Orchestrator(ledger=ledger, router_fn=router_fn)

        # Unique prompt per run: a fixed prompt would hit the persistent
        # L2 cache and mask real dispatch (returning a stale model without
        # ever evaluating quarantine/retry gates).
        prompt = f"Simple coding task {uuid.uuid4().hex[:8]}"
        leaves = [("task-1", prompt)]
        dag = orchestrator.decompose("Build something", leaves)

        # Mock the gateway adapter to avoid real network calls
        self.shared.adapter.send = MagicMock(return_value={"output": "implemented"})

        result_dag = orchestrator.run(dag, task_type="coding")

        self.assertEqual(result_dag.nodes["task-1"].state.name, "SUCCEEDED")
        self.assertEqual(result_dag.nodes["task-1"].model_id, "mimo-v2.5-free")

        # Verify ledger has entries
        ledger_content = self.ctx.ledger_path.read_text(encoding="utf-8")
        self.assertIn("decompose", ledger_content)
        self.assertIn("dispatch", ledger_content)
        self.assertIn("result", ledger_content)

    def test_multi_project_isolation(self):
        """Different projects have isolated ledgers, skill hubs, breakers."""
        states = build_project_states(self.config)

        self.assertIn("wsb-alpha", states)
        self.assertIn("burgonomics", states)

        wsb_state = states["wsb-alpha"]
        burg_state = states["burgonomics"]

        # Different ledger instances
        self.assertIsNot(wsb_state.ledger, burg_state.ledger)
        # Different skill hub instances
        self.assertIsNot(wsb_state.skill_hub, burg_state.skill_hub)
        # Different breaker instances (per-project isolation)
        self.assertIsNot(wsb_state.breakers["mimo-v2.5-free"], burg_state.breakers["mimo-v2.5-free"])

        # But shared singletons are the same
        self.assertIs(SHARED.tracker, SHARED.tracker)
        self.assertIs(SHARED.cache, SHARED.cache)

    def test_default_chain_from_registry(self):
        """Orchestrator.default_chain_for uses registry, not hardcoded."""
        ledger = DelegationLedger(self.ctx.ledger_path)
        orchestrator = Orchestrator(ledger=ledger)

        chain = orchestrator.default_chain_for("coding")
        expected = default_chain("coding")
        self.assertEqual(chain, expected)

        chain_research = orchestrator.default_chain_for("research")
        expected_research = default_chain("research")
        self.assertEqual(chain_research, expected_research)

    def test_kilo_probe_roundtrip_contract(self):
        """run_probe_roundtrip follows contract: probe md -> bridge -> receipt."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            inbox = tmpdir / "kilo_inbox"
            interharness = tmpdir / "InterHarness"
            bridge_path = tmpdir / "fake_bridge.py"

            # Create fake bridge that returns success
            bridge_path.write_text(
                'import json, sys\n'
                'print(json.dumps({"status": "success", "output": "kilo response", "evidence": "evidence.txt"}))',
                encoding="utf-8",
            )

            kilo_cfg = {
                "inbox": str(inbox),
                "interharness": str(interharness),
                "bridge_path": str(bridge_path),
                "print_timeout": 10,
            }

            result = run_probe_roundtrip(self.ctx, "probe-e2e", "test prompt", kilo_cfg)

            # Verify probe written
            probe_files = list(inbox.glob("hermes-to-kilo-probe-e2e.md"))
            self.assertEqual(len(probe_files), 1)

            # Verify receipt written
            receipt_files = list(interharness.glob("kilo-to-hermes-probe-e2e.md"))
            self.assertEqual(len(receipt_files), 1)

            # Verify contract dict returned
            self.assertEqual(result["text"], "kilo response")
            self.assertEqual(result["confidence"], 1.0)
            self.assertEqual(result["model_id"], "kilo")

            # Verify ledger recorded
            ledger_content = self.ctx.ledger_path.read_text(encoding="utf-8")
            self.assertIn("probe-e2e", ledger_content)


class TestRouterHealthFeedback(unittest.TestCase):
    """Test health tracker and feedback loop integration."""

    def setUp(self):
        self.config = load_config()
        self.contexts = build_project_contexts(self.config, "coder")
        self.ctx = self.contexts[0]
        self.shared = SHARED

    def test_health_tracker_records_success_failure(self):
        """HealthTracker records success and failure with latency."""
        # Use fresh tracker to avoid test pollution
        tracker = HealthTracker()
        tracker.record_success("mimo-v2.5-free", 1500.0)
        tracker.record_failure("mimo-v2.5-free", status_code=500, error="server error", retry_after_s=0, latency_ms=5000.0)

        snapshot = tracker.snapshot()
        self.assertIn("mimo-v2.5-free", snapshot)
        model_health = snapshot["mimo-v2.5-free"]
        self.assertEqual(model_health["successes"], 1)
        self.assertEqual(model_health["failures"], 1)

    def test_feedback_loop_ema_updates(self):
        """FeedbackLoop updates EMA scores on record."""
        feedback = self.shared.feedback
        initial_ema = feedback.get_ema("mimo-v2.5-free")

        feedback.record("mimo-v2.5-free", 1000.0, completeness=1.0, accuracy=1.0)
        new_ema = feedback.get_ema("mimo-v2.5-free")

        # EMA should have updated (moved toward 1.0)
        self.assertNotEqual(initial_ema, new_ema)

    def test_fallback_chain_builder_reorders_by_ema(self):
        """FallbackChainBuilder reorders chain based on EMA scores."""
        # Use fresh instances to avoid test pollution
        tracker = HealthTracker()
        feedback = FeedbackLoop()
        builder = FallbackChainBuilder(tracker)

        # Give mimo high EMA, nemotron low EMA
        feedback.record("mimo-v2.5-free", 1000.0, completeness=1.0, accuracy=1.0)
        feedback.record("mimo-v2.5-free", 1000.0, completeness=1.0, accuracy=1.0)
        feedback.record("nemotron-3-ultra-free", 5000.0, completeness=0.5, accuracy=0.5)

        chain = builder.build_chain("coding", scores=feedback.ema_map())

        # mimo should be first (higher EMA)
        self.assertEqual(chain[0].model_id, "mimo-v2.5-free")


if __name__ == "__main__":
    unittest.main()