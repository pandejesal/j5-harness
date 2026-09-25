"""Unit tests for direct HTTP dispatch + gateway fallback (all mocked).

No network access: urlopen is stubbed, subprocess never spawned.
"""

from __future__ import annotations

import asyncio
import io
import json
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from tools.router.gateway_adapters import FallbackGateway, GatewayError
from tools.router.http_gateway import (
    HttpGatewayAdapter,
    provider_base_url,
    provider_key,
)


def _resp(payload: dict, status: int = 200, retry_after: str | None = None):
    resp = MagicMock()
    resp.status = status
    resp.headers = {"Retry-After": retry_after} if retry_after else {}
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _http_error(code: int, retry_after: str | None = None):
    headers = MagicMock()
    headers.get.return_value = retry_after
    return urllib.error.HTTPError(
        "http://x", code, "err", headers, io.BytesIO(b"{}"))


class ProviderTest(unittest.TestCase):
    def test_known_providers(self):
        self.assertTrue(provider_base_url("zen").startswith("https://"))
        self.assertTrue(provider_base_url("openrouter").startswith("https://"))
        self.assertTrue(provider_base_url("openai").startswith("https://"))

    def test_unknown_provider(self):
        with self.assertRaises(ValueError):
            provider_base_url("wat")
        with self.assertRaises(ValueError):
            provider_key("wat")

    def test_zen_keyless(self):
        with patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("J5_OPENROUTER_API_KEY", None)
            self.assertIsNone(provider_key("zen"))

    def test_key_from_env(self):
        with patch.dict("os.environ", {"J5_OPENROUTER_API_KEY": "sk-test"}):
            self.assertEqual(provider_key("openrouter"), "sk-test")

    def test_missing_key_raises(self):
        import os
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                HttpGatewayAdapter(provider="openrouter")


class HttpSendTest(unittest.TestCase):
    def _adapter(self):
        return HttpGatewayAdapter(provider="zen")

    def _payload(self, text="hello", total=50, inp=40, out=10):
        return {"choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                "usage": {"total_tokens": total, "prompt_tokens": inp,
                          "completion_tokens": out}}

    def test_success_extracts_text_and_usage(self):
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   return_value=_resp(self._payload())) as m:
            result = self._adapter().send("mimo-v2.5-free", "hi")
        self.assertEqual(result["output"], "hello")
        self.assertEqual(result["model"], "mimo-v2.5-free")
        self.assertEqual(result["usage"]["tokens_total"], 50)
        self.assertEqual(result["usage"]["tokens_input"], 40)
        url = m.call_args[0][0].full_url
        self.assertTrue(url.endswith("/chat/completions"))
        body = json.loads(m.call_args[0][0].data.decode("utf-8"))
        self.assertEqual(body["model"], "mimo-v2.5-free")
        self.assertEqual(body["messages"][0]["role"], "user")

    def test_auth_header_sent_when_keyed(self):
        adapter = HttpGatewayAdapter(provider="openrouter", api_key="sk-test")
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   return_value=_resp(self._payload())) as m:
            adapter.send("x/model", "hi")
        self.assertEqual(m.call_args[0][0].get_header("Authorization"), "Bearer sk-test")

    def test_rate_limit_maps_to_429(self):
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   side_effect=_http_error(429, "60")):
            with self.assertRaises(GatewayError) as ctx:
                self._adapter().send("mimo-v2.5-free", "hi")
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertEqual(ctx.exception.retry_after_s, 60.0)

    def test_auth_failure_maps_to_401(self):
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   side_effect=_http_error(401)):
            with self.assertRaises(GatewayError) as ctx:
                self._adapter().send("mimo-v2.5-free", "hi")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_transport_error(self):
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   side_effect=OSError("dns down")):
            with self.assertRaises(GatewayError):
                self._adapter().send("mimo-v2.5-free", "hi")

    def test_empty_choices_raises(self):
        with patch("tools.router.http_gateway.urllib.request.urlopen",
                   return_value=_resp({"choices": []})):
            with self.assertRaises(GatewayError):
                self._adapter().send("mimo-v2.5-free", "hi")

    def test_busy_refuses_second_dispatch(self):
        adapter = self._adapter()
        adapter._in_flight = 1
        with self.assertRaises(GatewayError):
            asyncio.run(adapter.asend("mimo-v2.5-free", "hi"))


class StubGateway:
    """Minimal GatewayInterface double for fallback tests."""

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error
        self.calls = 0

    async def asend(self, model, prompt):
        self.calls += 1
        if self._error is not None:
            raise self._error
        return self._result

    def send(self, model, prompt, timeout_s=60.0, **kwargs):
        return asyncio.run(self.asend(model, prompt))


class FallbackGatewayTest(unittest.TestCase):
    def test_empty_chain_rejected(self):
        with self.assertRaises(ValueError):
            FallbackGateway([])

    def test_first_success_wins(self):
        first = StubGateway(result={"output": "one"})
        second = StubGateway(result={"output": "two"})
        out = asyncio.run(FallbackGateway([first, second]).asend("m", "p"))
        self.assertEqual(out, {"output": "one"})
        self.assertEqual(second.calls, 0)

    def test_falls_through_to_standby(self):
        dead = StubGateway(error=GatewayError("cli exploded"))
        live = StubGateway(result={"output": "via http"})
        out = asyncio.run(FallbackGateway([dead, live]).asend("m", "p"))
        self.assertEqual(out, {"output": "via http"})
        self.assertEqual(dead.calls, 1)
        self.assertEqual(live.calls, 1)

    def test_all_fail_raises_last_error(self):
        first = StubGateway(error=GatewayError("boom-1"))
        second = StubGateway(error=GatewayError("boom-2", status_code=429))
        with self.assertRaises(GatewayError) as ctx:
            asyncio.run(FallbackGateway([first, second]).asend("m", "p"))
        self.assertIn("boom-2", str(ctx.exception))
        self.assertEqual(ctx.exception.status_code, 429)

    def test_singleton_behaves_like_wrapped(self):
        only = StubGateway(result={"output": "solo"})
        out = asyncio.run(FallbackGateway([only]).asend("m", "p"))
        self.assertEqual(out, {"output": "solo"})


if __name__ == "__main__":
    unittest.main()
