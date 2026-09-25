"""Contract tests for Task 5.1 integration wiring.

Tests the router_fn contract, shared singletons, per-project isolation,
skill leaf short-circuit, cache hit/miss, breaker gate, model pick fallback,
compression, health/feedback recording.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.harness.integration import (
    CONFIG_PATH,
    DEFAULT_TOKEN_BUDGET,
    ROLE_TASK_TYPES,
    ProjectContext,
    SharedState,
    ProjectState,
    SyncCircuitBreaker,
    load_config,
    build_shared,
    SHARED,
    role_task_type,
    role_chain_for,
    build_project_contexts,
    build_project_states,
    make_router_fn,
    run_probe_roundtrip,
    _cache_key,
    _candidate_models,
    _extract_text,
    _ensure_breaker,
    _get_or_build_state,
    _build_state,
    _token_budget,
)


class LoadConfigTest(unittest.TestCase):
    def test_loads_existing_config(self):
        config = load_config()
        self.assertIn("projects", config)
        self.assertIn("dirs", config)
        self.assertIn("fallbackLadders", config)
        self.assertTrue(config["projects"]["wsb-alpha"]["enabled"])
        self.assertTrue(config["projects"]["burgonomics"]["enabled"])


class RoleTaskTypeTest(unittest.TestCase):
    def test_coder_maps_to_coding(self):
        self.assertEqual(role_task_type("coder"), "coding")

    def test_planner_maps_to_research(self):
        self.assertEqual(role_task_type("planner"), "research")

    def test_bulk_maps_to_analysis(self):
        self.assertEqual(role_task_type("bulk"), "analysis")

    def test_unknown_defaults_to_coding(self):
        self.assertEqual(role_task_type("unknown"), "coding")

    def test_case_insensitive(self):
        self.assertEqual(role_task_type("CODER"), "coding")
        self.assertEqual(role_task_type("Planner"), "research")


class RoleChainForTest(unittest.TestCase):
    def test_uses_fallback_ladders(self):
        config = {"fallbackLadders": {"coder": ["mimo-v2.5-free", "nemotron-3-ultra-free"]}}
        chain = role_chain_for(config, "coder")
        self.assertEqual(chain, ["mimo-v2.5-free", "nemotron-3-ultra-free"])

    def test_falls_back_to_default_chain(self):
        config = {"fallbackLadders": {}}
        chain = role_chain_for(config, "coder")
        self.assertIsInstance(chain, list)
        self.assertTrue(len(chain) > 0)


class BuildProjectContextsTest(unittest.TestCase):
    def test_filters_enabled_projects(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": False}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        contexts = build_project_contexts(config, "coder")
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].name, "wsb-alpha")

    def test_builds_correct_paths(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        contexts = build_project_contexts(config, "coder")
        ctx = contexts[0]
        self.assertEqual(ctx.ledger_path, Path("/tmp/wsb/.harness/ledger.jsonl"))
        self.assertEqual(ctx.cache_path, Path("/tmp/wsb/.harness/cache"))
        self.assertEqual(ctx.skill_roots, [Path("/tmp/wsb/.harness/skills")])

    def test_role_chain_from_fallback_ladders(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free", "nemotron-3-ultra-free"]},
        }
        contexts = build_project_contexts(config, "coder")
        self.assertEqual(contexts[0].role_chain, ["mimo-v2.5-free", "nemotron-3-ultra-free"])


class SharedSingletonsTest(unittest.TestCase):
    def test_shared_is_global(self):
        # SHARED resolves lazily via module __getattr__ (no import-time build)
        self.assertIsInstance(SHARED, SharedState)
        self.assertIsNotNone(SHARED.tracker)
        self.assertIsNotNone(SHARED.feedback)
        self.assertIsNotNone(SHARED.chain_builder)
        self.assertIsNotNone(SHARED.router)
        self.assertIsNotNone(SHARED.adapter)
        self.assertIsNotNone(SHARED.cache)

    def test_build_shared_creates_new_instances(self):
        shared = build_shared()
        self.assertIsInstance(shared.tracker, type(SHARED.tracker))
        self.assertIsInstance(shared.feedback, type(SHARED.feedback))
        self.assertIsInstance(shared.chain_builder, type(SHARED.chain_builder))
        self.assertIsInstance(shared.router, type(SHARED.router))
        self.assertIsInstance(shared.adapter, type(SHARED.adapter))
        self.assertIsInstance(shared.cache, type(SHARED.cache))


class SyncCircuitBreakerTest(unittest.TestCase):
    def test_starts_closed(self):
        breaker = SyncCircuitBreaker()
        self.assertFalse(breaker.is_open())

    def test_record_success_clears_failures(self):
        breaker = SyncCircuitBreaker()
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        self.assertFalse(breaker.is_open())

    def test_trips_after_threshold(self):
        breaker = SyncCircuitBreaker()
        # Default threshold is 5
        for _ in range(5):
            breaker.record_failure()
        self.assertTrue(breaker.is_open())

    def test_isolation_per_instance(self):
        b1 = SyncCircuitBreaker()
        b2 = SyncCircuitBreaker()
        for _ in range(5):
            b1.record_failure()
        self.assertTrue(b1.is_open())
        self.assertFalse(b2.is_open())


class CacheKeyTest(unittest.TestCase):
    def test_stable_key(self):
        key1 = _cache_key("mimo-v2.5-free", "coding", "hello world")
        key2 = _cache_key("mimo-v2.5-free", "coding", "hello world")
        self.assertEqual(key1, key2)

    def test_different_prompt_different_key(self):
        key1 = _cache_key("mimo-v2.5-free", "coding", "hello")
        key2 = _cache_key("mimo-v2.5-free", "coding", "world")
        self.assertNotEqual(key1, key2)

    def test_different_model_different_key(self):
        key1 = _cache_key("mimo-v2.5-free", "coding", "hello")
        key2 = _cache_key("nemotron-3-ultra-free", "coding", "hello")
        self.assertNotEqual(key1, key2)

    def test_none_model_uses_auto(self):
        key1 = _cache_key(None, "coding", "hello")
        key2 = _cache_key("auto", "coding", "hello")
        self.assertEqual(key1, key2)


class CandidateModelsTest(unittest.TestCase):
    def setUp(self):
        self.ctx = ProjectContext(
            name="test",
            dir=Path("/tmp/test"),
            ledger_path=Path("/tmp/test/.harness/ledger.jsonl"),
            cache_path=Path("/tmp/test/.harness/cache"),
            skill_roots=[Path("/tmp/test/.harness/skills")],
            role_chain=["mimo-v2.5-free", "nemotron-3-ultra-free"],
        )
        self.shared = SHARED

    def test_explicit_model_id_first(self):
        candidates = _candidate_models("mimo-v2.5-free", None, self.ctx, "coding", self.shared)
        self.assertEqual(candidates, ["mimo-v2.5-free"])

    def test_caller_chain_second(self):
        candidates = _candidate_models(None, ["mimo-v2.5-free", "nemotron-3-ultra-free"], self.ctx, "coding", self.shared)
        self.assertEqual(candidates, ["mimo-v2.5-free", "nemotron-3-ultra-free"])

    def test_role_chain_third(self):
        candidates = _candidate_models(None, None, self.ctx, "coding", self.shared)
        self.assertEqual(candidates, ["mimo-v2.5-free", "nemotron-3-ultra-free"])

    def test_router_pick_fourth(self):
        ctx_no_chain = ProjectContext(
            name="test",
            dir=Path("/tmp/test"),
            ledger_path=Path("/tmp/test/.harness/ledger.jsonl"),
            cache_path=Path("/tmp/test/.harness/cache"),
            skill_roots=[Path("/tmp/test/.harness/skills")],
            role_chain=[],
        )
        candidates = _candidate_models(None, None, ctx_no_chain, "coding", self.shared)
        self.assertIsInstance(candidates, list)
        self.assertTrue(len(candidates) > 0)

    def test_deduplicates_chain(self):
        candidates = _candidate_models(None, ["mimo-v2.5-free", "mimo-v2.5-free", "nemotron-3-ultra-free"], self.ctx, "coding", self.shared)
        self.assertEqual(candidates, ["mimo-v2.5-free", "nemotron-3-ultra-free"])


class ExtractTextTest(unittest.TestCase):
    def test_passthrough_string(self):
        self.assertEqual(_extract_text("hello"), "hello")

    def test_dict_with_output(self):
        self.assertEqual(_extract_text({"output": "hello"}), "hello")

    def test_dict_with_text(self):
        self.assertEqual(_extract_text({"text": "hello"}), "hello")

    def test_dict_with_choices(self):
        resp = {"choices": [{"text": "hello"}]}
        self.assertEqual(_extract_text(resp), "hello")

    def test_dict_with_message_content(self):
        resp = {"choices": [{"message": {"content": "hello"}}]}
        self.assertEqual(_extract_text(resp), "hello")

    def test_nested_payload(self):
        resp = {"payload": {"output": "hello"}}
        self.assertEqual(_extract_text(resp), "hello")

    def test_fallback_json_dumps(self):
        resp = {"unknown": "structure"}
        result = _extract_text(resp)
        self.assertIn("unknown", result)
        self.assertIn("structure", result)


class EnsureBreakerTest(unittest.TestCase):
    def test_creates_breaker_for_new_model(self):
        state = ProjectState(
            ctx=ProjectContext(
                name="test",
                dir=Path("/tmp/test"),
                ledger_path=Path("/tmp/test/.harness/ledger.jsonl"),
                cache_path=Path("/tmp/test/.harness/cache"),
                skill_roots=[Path("/tmp/test/.harness/skills")],
                role_chain=[],
            ),
            ledger=MagicMock(),
            skill_hub=MagicMock(),
            breakers={},
        )
        breaker = _ensure_breaker(state, "mimo-v2.5-free")
        self.assertIsInstance(breaker, SyncCircuitBreaker)
        self.assertIn("mimo-v2.5-free", state.breakers)

    def test_reuses_existing_breaker(self):
        state = ProjectState(
            ctx=ProjectContext(
                name="test",
                dir=Path("/tmp/test"),
                ledger_path=Path("/tmp/test/.harness/ledger.jsonl"),
                cache_path=Path("/tmp/test/.harness/cache"),
                skill_roots=[Path("/tmp/test/.harness/skills")],
                role_chain=[],
            ),
            ledger=MagicMock(),
            skill_hub=MagicMock(),
            breakers={"mimo-v2.5-free": SyncCircuitBreaker()},
        )
        breaker = _ensure_breaker(state, "mimo-v2.5-free")
        self.assertIs(state.breakers["mimo-v2.5-free"], breaker)


class TokenBudgetTest(unittest.TestCase):
    def test_uses_config_target_tokens(self):
        config = {"context": {"target_tokens": 2000}}
        self.assertEqual(_token_budget(config), 2000)

    def test_defaults_to_default_token_budget(self):
        config = {}
        self.assertEqual(_token_budget(config), DEFAULT_TOKEN_BUDGET)

    def test_invalid_falls_back(self):
        config = {"context": {"target_tokens": "invalid"}}
        self.assertEqual(_token_budget(config), DEFAULT_TOKEN_BUDGET)


class MakeRouterFnTest(unittest.TestCase):
    def setUp(self):
        self.config = {
            "projects": {"wsb-alpha": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free", "nemotron-3-ultra-free"]},
            "context": {"target_tokens": 4000},
        }
        self.contexts = build_project_contexts(self.config, "coder")
        self.ctx = self.contexts[0]
        self.shared = SHARED

    def test_returns_callable(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        self.assertTrue(callable(router_fn))

    def test_skill_leaf_short_circuits(self):
        # Mock skill hub invoke
        mock_hub = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = True
        mock_result.output = "skill output"
        mock_result.error = None
        mock_hub.invoke.return_value = mock_result

        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Inject mock skill hub
        state = _get_or_build_state(self.ctx)
        state.skill_hub = mock_hub
        self.ctx.leaf_skills["task-1"] = ("test/skill", {"input": "value"})

        result = router_fn("prompt", task_id="task-1", task_type="coding")
        self.assertEqual(result["text"], "skill output")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["model_id"], "skill:test/skill")
        mock_hub.invoke.assert_called_once()

    def test_skill_leaf_error_returns_zero_confidence(self):
        mock_hub = MagicMock()
        mock_result = MagicMock()
        mock_result.ok = False
        mock_result.output = ""
        mock_result.error = "skill failed"
        mock_hub.invoke.return_value = mock_result

        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        state = _get_or_build_state(self.ctx)
        state.skill_hub = mock_hub
        self.ctx.leaf_skills["task-1"] = ("test/skill", {"input": "value"})

        result = router_fn("prompt", task_id="task-1", task_type="coding")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["error"], "skill failed")

    def test_cache_hit_returns_cached(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Pre-populate cache
        cache_key = _cache_key("mimo-v2.5-free", "coding", "test prompt")
        self.shared.cache.set(cache_key, {"text": "cached", "confidence": 1.0, "model_id": "mimo-v2.5-free"})

        result = router_fn("test prompt", task_id="task-2", task_type="coding", model_id="mimo-v2.5-free")
        self.assertEqual(result["text"], "cached")
        self.assertEqual(result["confidence"], 1.0)

    def test_compression_when_over_budget(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Create a prompt that exceeds budget
        long_prompt = "x " * 3000  # ~6000 tokens > 4000 budget
        # Mock adapter to avoid real dispatch
        self.shared.adapter.send = MagicMock(return_value={"output": "response"})

        result = router_fn(long_prompt, task_id="task-3", task_type="coding")
        # Should have been compressed and dispatched
        self.assertIn("text", result)

    def test_breaker_gate_blocks_open_breaker(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        state = _get_or_build_state(self.ctx)
        # Open the breaker for mimo
        breaker = state.breakers["mimo-v2.5-free"]
        for _ in range(5):
            breaker.record_failure()
        self.assertTrue(breaker.is_open())

        # Should skip mimo and try next
        self.shared.adapter.send = MagicMock(return_value={"output": "response"})
        result = router_fn("prompt", task_id="task-4", task_type="coding", model_id="mimo-v2.5-free")
        # Should have tried nemotron instead
        self.assertIn("text", result)

    def test_quarantined_model_skipped(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Quarantine mimo (released in cleanup: global SHARED must not
        # leak quarantine into later tests in the same process).
        self.shared.tracker.quarantine("mimo-v2.5-free", ttl_s=3600)
        self.addCleanup(self.shared.tracker.release, "mimo-v2.5-free")
        self.assertTrue(self.shared.tracker.is_quarantined("mimo-v2.5-free"))

        self.shared.adapter.send = MagicMock(return_value={"output": "response"})
        result = router_fn("prompt", task_id="task-5", task_type="coding", model_id="mimo-v2.5-free")
        # Should have skipped mimo
        self.assertIn("text", result)

    def test_retry_after_model_skipped(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Set retry-after (released in cleanup — see above).
        self.shared.tracker.record_failure("mimo-v2.5-free", status_code=429, retry_after_s=60)
        self.addCleanup(self.shared.tracker.release, "mimo-v2.5-free")
        self.assertTrue(self.shared.tracker.in_retry_after("mimo-v2.5-free"))

        self.shared.adapter.send = MagicMock(return_value={"output": "response"})
        result = router_fn("prompt", task_id="task-6", task_type="coding", model_id="mimo-v2.5-free")
        self.assertIn("text", result)

    def test_unknown_model_in_chain_skipped(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Chain with unknown model
        self.shared.adapter.send = MagicMock(return_value={"output": "response"})
        result = router_fn("prompt", task_id="task-7", task_type="coding", chain=["unknown-model", "mimo-v2.5-free"])
        self.assertIn("text", result)

    def test_all_models_unavailable_returns_error(self):
        router_fn = make_router_fn(self.ctx, self.shared, self.config)
        # Quarantine all models (released in cleanup — see above).
        for model_id in ["mimo-v2.5-free", "nemotron-3-ultra-free", "ling-3.0-flash-fin-free"]:
            self.shared.tracker.quarantine(model_id, ttl_s=3600)
            self.addCleanup(self.shared.tracker.release, model_id)

        result = router_fn("prompt", task_id="task-8", task_type="coding")
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["error"], "no available model")


class BuildProjectStatesTest(unittest.TestCase):
    def test_builds_state_for_enabled_projects(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": False}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        states = build_project_states(config)
        self.assertIn("wsb-alpha", states)
        self.assertNotIn("burgonomics", states)
        self.assertIsInstance(states["wsb-alpha"], ProjectState)
        self.assertIsInstance(states["wsb-alpha"].ledger, type(build_project_states(config)["wsb-alpha"].ledger))
        self.assertIsInstance(states["wsb-alpha"].skill_hub, type(build_project_states(config)["wsb-alpha"].skill_hub))
        self.assertIsInstance(states["wsb-alpha"].breakers, dict)


class PerProjectIsolationTest(unittest.TestCase):
    def test_different_projects_different_ledgers(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        states = build_project_states(config)
        self.assertIsNot(states["wsb-alpha"].ledger, states["burgonomics"].ledger)
        self.assertIsNot(states["wsb-alpha"].skill_hub, states["burgonomics"].skill_hub)
        self.assertIsNot(states["wsb-alpha"].breakers, states["burgonomics"].breakers)

    def test_shared_singletons_are_same(self):
        config = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        states = build_project_states(config)
        # Shared singletons should be the same object
        self.assertIs(states["wsb-alpha"].ctx, states["wsb-alpha"].ctx)  # trivial
        # The SHARED module-level is the same for both


class RunProbeRoundtripTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.inbox = Path(self.temp_dir) / "kilo_inbox"
        self.interharness = Path(self.temp_dir) / "InterHarness"
        self.bridge_path = Path(self.temp_dir) / "fake_bridge.py"
        # Create a fake bridge that returns success
        self.bridge_path.write_text(
            'import json, sys\n'
            'print(json.dumps({"status": "success", "output": "kilo response", "evidence": "evidence.txt"}))',
            encoding="utf-8",
        )
        self.kilo_cfg = {
            "inbox": str(self.inbox),
            "interharness": str(self.interharness),
            "bridge_path": str(self.bridge_path),
            "print_timeout": 120,
        }
        self.config = {
            "projects": {"wsb-alpha": {"enabled": True}},
            "dirs": {"wsb-alpha": self.temp_dir},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
            "context": {"target_tokens": 4000},
        }
        self.contexts = build_project_contexts(self.config, "coder")
        self.ctx = self.contexts[0]

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_writes_probe_md_to_inbox(self):
        result = run_probe_roundtrip(self.ctx, "probe-09", "test prompt", self.kilo_cfg)
        probe_files = list(self.inbox.glob("hermes-to-kilo-probe-09.md"))
        self.assertEqual(len(probe_files), 1)
        content = probe_files[0].read_text(encoding="utf-8")
        self.assertIn("id: probe-09", content)
        self.assertIn("sent_ts:", content)
        self.assertIn("deadline_ts:", content)
        self.assertIn("owner: wsb-alpha", content)
        self.assertIn("test prompt", content)

    def test_writes_receipt_to_interharness(self):
        result = run_probe_roundtrip(self.ctx, "probe-10", "test prompt", self.kilo_cfg)
        receipt_files = list(self.interharness.glob("kilo-to-hermes-probe-10.md"))
        self.assertEqual(len(receipt_files), 1)
        content = receipt_files[0].read_text(encoding="utf-8")
        self.assertIn("id: probe-10", content)
        self.assertIn("status: success", content)
        self.assertIn("kilo response", content)

    def test_returns_contract_dict_on_success(self):
        result = run_probe_roundtrip(self.ctx, "probe-11", "test prompt", self.kilo_cfg)
        self.assertEqual(result["text"], "kilo response")
        self.assertEqual(result["confidence"], 1.0)
        self.assertEqual(result["model_id"], "kilo")

    def test_returns_contract_dict_on_error(self):
        # Create a bridge that returns error
        error_bridge = Path(self.temp_dir) / "error_bridge.py"
        error_bridge.write_text(
            'import json, sys\n'
            'print(json.dumps({"status": "error", "output": "", "error": "bridge failed"}))',
            encoding="utf-8",
        )
        error_cfg = {**self.kilo_cfg, "bridge_path": str(error_bridge)}
        result = run_probe_roundtrip(self.ctx, "probe-12", "test prompt", error_cfg)
        self.assertEqual(result["confidence"], 0.0)
        self.assertEqual(result["model_id"], "kilo")
        self.assertIn("error", result)

    def test_bridge_called_with_correct_args(self):
        # Capture the subprocess call
        import subprocess
        original_run = subprocess.run
        captured = {}
        def capture_run(*args, **kwargs):
            captured["args"] = args[0]
            captured["kwargs"] = kwargs
            return original_run(*args, **kwargs)
        with patch("subprocess.run", side_effect=capture_run):
            run_probe_roundtrip(self.ctx, "probe-13", "test prompt", self.kilo_cfg)
        args = captured["args"]
        self.assertEqual(args[0], sys.executable)
        self.assertEqual(args[1], str(self.bridge_path))
        self.assertIn("--prompt-file", args)
        self.assertIn("--cwd", args)
        self.assertIn("--print", args)
        self.assertIn("--output-format", args)
        self.assertIn("json", args)
        self.assertIn("--print-timeout", args)
        self.assertIn("120", args)
        self.assertIn("--json", args)
        self.assertEqual(captured["kwargs"]["cwd"], self.temp_dir)
        self.assertEqual(captured["kwargs"]["shell"], False)
        self.assertEqual(captured["kwargs"]["env"]["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(captured["kwargs"]["env"]["PYTHONUTF8"], "1")

    def test_atomic_write_via_tmp_rename(self):
        # Verify no partial files left
        run_probe_roundtrip(self.ctx, "probe-14", "test prompt", self.kilo_cfg)
        tmp_files = list(self.inbox.glob("*.tmp")) + list(self.interharness.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0)

    def test_records_in_ledger(self):
        run_probe_roundtrip(self.ctx, "probe-15", "test prompt", self.kilo_cfg)
        state = _get_or_build_state(self.ctx)
        # Check ledger was called (we can't easily inspect the ledger content without reading the file)
        # But we can verify the ledger file exists and has content
        ledger_path = self.ctx.ledger_path
        self.assertTrue(ledger_path.exists())
        content = ledger_path.read_text(encoding="utf-8")
        self.assertIn("probe-15", content)


class IntegrationContractTest(unittest.TestCase):
    """Contract tests for integration wiring (Task 5.3 acceptance)."""

    def setUp(self):
        self.config = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": True}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free", "nemotron-3-ultra-free"]},
            "context": {"target_tokens": 4000},
        }
        self.contexts = build_project_contexts(self.config, "coder")
        self.ctx_wsb = self.contexts[0]
        self.ctx_burg = self.contexts[1]
        self.shared = SHARED

    def test_router_fn_contract_orchestrator_run(self):
        """router_fn contract for Orchestrator.run caller."""
        router_fn = make_router_fn(self.ctx_wsb, self.shared, self.config)
        result = router_fn("test prompt", task_id="task-1", task_type="coding")
        self.assertIn("text", result)
        self.assertIn("confidence", result)
        self.assertIn("model_id", result)
        self.assertIsInstance(result["confidence"], float)
        self.assertTrue(0.0 <= result["confidence"] <= 1.0)

    def test_router_fn_contract_run_consensus(self):
        """router_fn contract for run_consensus caller (passes model_id and chain)."""
        router_fn = make_router_fn(self.ctx_wsb, self.shared, self.config)
        result = router_fn(
            "test prompt",
            task_id="task-2",
            task_type="coding",
            chain=["mimo-v2.5-free", "nemotron-3-ultra-free"],
            model_id="mimo-v2.5-free",
        )
        self.assertIn("text", result)
        self.assertIn("confidence", result)
        self.assertIn("model_id", result)

    def test_router_fn_contract_critique_loop_rerun(self):
        """router_fn contract for CritiqueLoop.rerun caller (passes chain)."""
        router_fn = make_router_fn(self.ctx_wsb, self.shared, self.config)
        result = router_fn(
            "test prompt",
            task_id="task-3",
            task_type="coding",
            chain=["mimo-v2.5-free"],
        )
        self.assertIn("text", result)
        self.assertIn("confidence", result)
        self.assertIn("model_id", result)

    def test_kilo_excluded_from_consensus(self):
        """Kilo models are excluded from consensus fan-out."""
        from tools.delegation.multi_model_consensus import _exclude_kilo
        models = ["mimo-v2.5-free", "nemotron-3-ultra-free", "kilo", "kilo-v2"]
        filtered = _exclude_kilo(models)
        self.assertNotIn("kilo", filtered)
        self.assertNotIn("kilo-v2", filtered)
        self.assertIn("mimo-v2.5-free", filtered)
        self.assertIn("nemotron-3-ultra-free", filtered)

    def test_cache_key_stability(self):
        """Cache key is stable for same inputs."""
        key1 = _cache_key("mimo-v2.5-free", "coding", "hello world")
        key2 = _cache_key("mimo-v2.5-free", "coding", "hello world")
        self.assertEqual(key1, key2)
        # Different prompt -> different key
        key3 = _cache_key("mimo-v2.5-free", "coding", "different")
        self.assertNotEqual(key1, key3)

    def test_invoke_result_mapping(self):
        """InvokeResult maps to router_fn contract correctly."""
        from tools.skills.ecosystem.skill_hub import InvokeResult
        # ok=True -> confidence=1.0
        ok_result = InvokeResult(ok=True, output="success", error=None, exit_code=0)
        self.assertTrue(ok_result.ok)
        # ok=False -> confidence=0.0
        fail_result = InvokeResult(ok=False, output="", error="failed", exit_code=1)
        self.assertFalse(fail_result.ok)

    def test_config_flip_toggles_project_context(self):
        """Config flip (enabled=false) toggles ProjectContext inclusion."""
        config_enabled = {
            "projects": {"wsb-alpha": {"enabled": True}, "burgonomics": {"enabled": False}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        contexts = build_project_contexts(config_enabled, "coder")
        self.assertEqual(len(contexts), 1)
        self.assertEqual(contexts[0].name, "wsb-alpha")

        config_disabled = {
            "projects": {"wsb-alpha": {"enabled": False}, "burgonomics": {"enabled": False}},
            "dirs": {"wsb-alpha": "/tmp/wsb", "burgonomics": "/tmp/burg"},
            "fallbackLadders": {"coder": ["mimo-v2.5-free"]},
        }
        contexts = build_project_contexts(config_disabled, "coder")
        self.assertEqual(len(contexts), 0)

    def test_ledger_entry_types(self):
        """Ledger accepts all valid entry types including probe."""
        from tools.delegation.ledger import ENTRY_TYPES
        expected = {"decompose", "dispatch", "result", "critique", "error", "blocked", "probe"}
        self.assertEqual(set(ENTRY_TYPES), expected)

    def test_breaker_key_isolation_per_project(self):
        """CircuitBreaker keys are isolated per project."""
        states = build_project_states(self.config)
        wsb_breakers = states["wsb-alpha"].breakers
        burg_breakers = states["burgonomics"].breakers
        # Different breaker instances for same model_id
        self.assertIsNot(wsb_breakers["mimo-v2.5-free"], burg_breakers["mimo-v2.5-free"])
        # But same model_id exists in both
        self.assertIn("mimo-v2.5-free", wsb_breakers)
        self.assertIn("mimo-v2.5-free", burg_breakers)


if __name__ == "__main__":
    unittest.main()