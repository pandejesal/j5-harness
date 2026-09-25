"""Reputation-aware feedback: doom-loop and correction signals.

Adapted concept: per-agent evaluation (dispatch/success/failure/correction/
doom_loop) from evsmem feeds the router EMA, so failing models lose rank
instead of coasting on stale scores. Failures previously never touched
feedback at all — only the health tracker saw them.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tools.router.feedback_loop import FeedbackLoop, score_response
from tools.router.gateway_adapters import GatewayError


class ScoreResponseTest(unittest.TestCase):
    def test_baseline_unchanged(self):
        # 0.4*0.9 (1s latency) + 0.3*1.0 + 0.3*1.0
        self.assertEqual(score_response(1000.0, 1.0, 1.0), 0.96)

    def test_doom_loop_halves(self):
        base = score_response(1000.0, 1.0, 1.0)
        self.assertEqual(score_response(1000.0, 1.0, 1.0, doom_loop=True),
                         round(base * 0.5, 4))

    def test_correction_penalty(self):
        base = score_response(1000.0, 1.0, 1.0)
        self.assertEqual(score_response(1000.0, 1.0, 1.0, correction=True),
                         round(base - 0.15, 4))

    def test_both_combine_with_floor(self):
        low = score_response(9000.0, 0.0, 0.0, doom_loop=True, correction=True)
        self.assertGreaterEqual(low, 0.0)
        self.assertLess(low, score_response(9000.0, 0.0, 0.0))


class RecordReputationTest(unittest.TestCase):
    def test_kwargs_accepted_and_surfaced(self):
        fb = FeedbackLoop()
        snap = fb.record("mimo-v2.5-free", 1000.0, 1.0, 1.0,
                         doom_loop=True, correction=True)
        self.assertTrue(snap["doom_loop"])
        self.assertTrue(snap["correction"])
        self.assertLess(snap["ema"], 0.5)

    def test_defaults_off(self):
        fb = FeedbackLoop()
        snap = fb.record("mimo-v2.5-free", 1000.0, 1.0, 1.0)
        self.assertFalse(snap["doom_loop"])
        self.assertFalse(snap["correction"])


class FailureFeedbackTest(unittest.TestCase):
    """Dispatch failures move the model EMA down (doom_loop on streaks)."""

    def test_failed_dispatch_records_doom_loop(self):
        from types import SimpleNamespace

        from tools.harness.integration import build_project_contexts, make_router_fn
        from tools.router.fallback_chain import FallbackChainBuilder
        from tools.router.free_model_router import FreeModelRouter
        from tools.router.health_probe import HealthTracker

        config = {
            "projects": {"wsb-alpha": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb-rep"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
            "context": {"target_tokens": 4000},
        }
        ctx = build_project_contexts(config, "coder")[0]
        tracker = HealthTracker()
        feedback = FeedbackLoop()
        adapter = MagicMock()
        adapter.send.side_effect = GatewayError("boom")
        cache = MagicMock()
        cache.get.return_value = None
        shared = SimpleNamespace(
            tracker=tracker, feedback=feedback,
            chain_builder=FallbackChainBuilder(tracker),
            router=FreeModelRouter(tracker=tracker, feedback=feedback),
            adapter=adapter, cache=cache,
        )
        # Seed a 3-failure streak (plain errors: no quarantine trip).
        for _ in range(3):
            tracker.record_failure("mimo-v2.5-free", error="earlier boom")
        self.assertFalse(tracker.is_quarantined("mimo-v2.5-free"))

        router_fn = make_router_fn(ctx, shared, config)
        result = router_fn("hi", task_id="t-rep-1", task_type="coding")

        self.assertEqual(result["confidence"], 0.0)
        self.assertLess(feedback.get_ema("mimo-v2.5-free"), 0.5)


if __name__ == "__main__":
    unittest.main()
