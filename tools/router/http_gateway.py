"""Direct HTTP dispatch backend: OpenAI-compatible chat completions over stdlib.

This is the independence layer: prompts can reach models WITHOUT the
opencode CLI installed, running, or healthy. Same ``GatewayInterface``
contract as every other adapter (``send`` returns a response dict with an
``output`` key; failures raise ``GatewayError`` with 429/401 codes), so
health tracking, fallback chains, breakers, ledger, and scoreboard keep
working unchanged.

Providers (OpenAI-compatible ``POST {base}/chat/completions``):
- ``zen``:        https://opencode.ai/zen/v1 (free tier, keyless/IP bucket —
  the same free models as CLI dispatch, no binary required)
- ``openrouter``: https://openrouter.ai/api/v1 (BYOK: J5_OPENROUTER_API_KEY)
- ``openai``:     https://api.openai.com/v1 (BYOK: J5_OPENAI_API_KEY)

Bring-your-own-keys: keys come ONLY from the environment, never from config
files, the bus, or the ledger. Unset key for a keyless provider (zen) is
fine; a missing key for a keyed provider raises ValueError at construction
(fail fast, not mid-dispatch).

Antigravity models stay CLI-routed (plugin auth has no HTTP equivalent);
see README providers section. Model ids pass through verbatim — configure
the provider's native id (e.g. ``mimo-v2.5-free`` on zen,
``anthropic/claude-sonnet-4-6`` on openrouter).

Stdlib only (urllib). No new dependencies.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import urllib.request

try:
    from tools.router.gateway_adapters import GatewayError, GatewayInterface
except ImportError:  # script-mode fallback
    from gateway_adapters import GatewayError, GatewayInterface  # type: ignore[no-redef]

PROVIDERS: dict[str, dict[str, object]] = {
    "zen": {
        "base_url": "https://opencode.ai/zen/v1",
        "key_env": None,  # keyless/IP bucket
        "note": "same free-tier models as CLI dispatch, no binary needed",
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "key_env": "J5_OPENROUTER_API_KEY",
        "note": "bring your own key; any model id OpenRouter serves",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "J5_OPENAI_API_KEY",
        "note": "bring your own key",
    },
}

DEFAULT_TIMEOUT_S = 120.0


def provider_base_url(name: str) -> str:
    try:
        return str(PROVIDERS[name]["base_url"])
    except KeyError:
        raise ValueError(f"unknown provider {name!r}; known: {sorted(PROVIDERS)}") from None


def provider_key(name: str) -> str | None:
    """Read the provider key from its env var (None when keyless/unset)."""
    try:
        env = PROVIDERS[name].get("key_env")
    except KeyError:
        raise ValueError(f"unknown provider {name!r}; known: {sorted(PROVIDERS)}") from None
    if not env:
        return None
    assert isinstance(env, str)
    return os.environ.get(env) or None


class HttpGatewayAdapter(GatewayInterface):
    """OpenAI-compatible HTTP dispatch with endpoint failover + serial gate."""

    def __init__(
        self,
        provider: str = "zen",
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        max_in_flight: int = 1,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = (base_url or provider_base_url(provider)).rstrip("/")
        if api_key is None:
            api_key = provider_key(provider)
        key_env = PROVIDERS[provider].get("key_env") if provider in PROVIDERS else None
        if key_env and not api_key:
            raise ValueError(
                f"provider {provider!r} needs an API key: set {key_env} "
                f"or pass api_key= explicitly (keys never live in config files)"
            )
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_in_flight = max(1, max_in_flight)
        self.extra_headers = dict(extra_headers or {})
        self._lock = threading.Lock()
        self._alock = asyncio.Lock()
        self._in_flight = 0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        headers.update(self.extra_headers)
        return headers

    def _post(self, model: str, prompt: str) -> dict:
        url = self.base_url + "/chat/completions"
        body = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                retry_after = resp.headers.get("Retry-After")
                try:
                    payload = json.loads(resp.read().decode("utf-8") or "{}")
                except ValueError:
                    payload = {}
                return {"endpoint": url, "status": resp.status,
                        "payload": payload, "retry_after": retry_after}
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            import urllib.error as _uerr

            retry_after: float | None = None
            if isinstance(exc, _uerr.HTTPError):
                raw = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    retry_after = float(raw) if raw else None
                except (TypeError, ValueError):
                    retry_after = None
                raise GatewayError(f"http {exc.code} from {self.provider}",
                                   status_code=exc.code,
                                   retry_after_s=retry_after) from exc
            raise GatewayError(str(exc)) from exc
        except OSError as exc:
            raise GatewayError(f"http transport error at {self.provider}: {exc}") from exc

    def _extract(self, response: dict, model: str) -> dict:
        """Fold OpenAI-shape payload into the router_fn contract dict."""
        payload = response.get("payload") or {}
        text = ""
        usage: dict = {}
        try:
            choices = payload.get("choices") or []
            if choices:
                message = (choices[0] or {}).get("message") or {}
                text = message.get("content") or ""
            raw_usage = payload.get("usage") or {}
            usage = {
                "tokens_total": raw_usage.get("total_tokens"),
                "tokens_input": raw_usage.get("prompt_tokens"),
                "tokens_output": raw_usage.get("completion_tokens"),
                "cost": 0,
                "finish_reason": (choices[0] or {}).get("finish_reason") if choices else None,
            }
        except (AttributeError, TypeError, IndexError):
            text, usage = "", {}
        if not isinstance(text, str) or not text:
            raise GatewayError(f"http {self.provider} returned no text for {model}")
        return {"output": text, "usage": usage, "model": model}

    def send(self, model: str, prompt: str, timeout_s: float | None = None,
             **kwargs: object) -> dict:
        """POST one chat completion; kwargs accepted for contract parity."""
        saved, self.timeout_s = self.timeout_s, timeout_s or self.timeout_s
        try:
            return self._extract(self._post(model, prompt), model)
        finally:
            self.timeout_s = saved

    async def asend(self, model: str, prompt: str) -> dict:
        async with self._alock:
            with self._lock:
                if self._in_flight >= self.max_in_flight:
                    raise GatewayError("dispatch serialized: gateway busy")
                self._in_flight += 1
            try:
                return await asyncio.to_thread(self.send, model, prompt)
            finally:
                with self._lock:
                    self._in_flight -= 1


__all__ = [
    "PROVIDERS",
    "DEFAULT_TIMEOUT_S",
    "provider_base_url",
    "provider_key",
    "HttpGatewayAdapter",
]
