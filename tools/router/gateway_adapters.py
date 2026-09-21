"""Gateway adapters: abstract interface + Zen multi-endpoint adapter.

Notes:
- The shared Zen free-tier key is bucketed per IP; all dispatch through
  this adapter is serialized (1 in-flight default) to respect that bucket.
- VPN rotation is advisory-only: this module reports the advisory string
  but never rotates networks itself.
"""

from __future__ import annotations

import abc
import asyncio
import json
import threading
import urllib.request
from dataclasses import dataclass

try:
    from tools.router.model_registry import ZEN_ENDPOINTS
except ImportError:  # script-mode fallback
    from model_registry import ZEN_ENDPOINTS  # type: ignore[no-redef]

VPN_ROTATION_ADVISORY = (
    "Advisory-only: the Zen free-tier key is rate-limited per IP bucket. "
    "If 429s persist across all endpoints, rotate the egress VPN endpoint "
    "manually, then wait for Retry-After to elapse. This router never "
    "rotates networks automatically."
)


def vpn_rotation_advisory() -> str:
    return VPN_ROTATION_ADVISORY


class GatewayError(Exception):
    def __init__(self, message: str, status_code: int | None = None,
                 retry_after_s: float | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retry_after_s = retry_after_s


class GatewayInterface(abc.ABC):
    """Abstract gateway: one async send + one sync convenience wrapper."""

    @abc.abstractmethod
    async def asend(self, model: str, prompt: str) -> dict:
        """Send prompt to model; return response dict; raise GatewayError."""
        raise NotImplementedError

    def send(self, model: str, prompt: str, timeout_s: float = 60.0,
             **kwargs: object) -> dict:
        # **kwargs (workdir, task_id, ...) accepted and ignored so every
        # gateway honors the same call contract as OpencodeCliAdapter.
        return asyncio.run(self.asend(model, prompt))


@dataclass
class ZenRequest:
    model: str
    prompt: str


class ZenGatewayAdapter(GatewayInterface):
    """Zen gateway with multi-endpoint failover (stdlib urllib only)."""

    def __init__(
        self,
        api_key: str | None = None,
        endpoints: tuple[str, ...] | list[str] | None = None,
        timeout_s: float = 30.0,
        max_in_flight: int = 1,
    ) -> None:
        self.api_key = api_key
        self.endpoints = list(endpoints) if endpoints else list(ZEN_ENDPOINTS)
        if not self.endpoints:
            raise ValueError("no endpoints configured")
        self.timeout_s = timeout_s
        self.max_in_flight = max(1, max_in_flight)
        self._lock = threading.Lock()
        self._alock = asyncio.Lock()
        self._in_flight = 0

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _post(self, endpoint: str, req: ZenRequest) -> dict:
        url = endpoint.rstrip("/") + "/chat"
        body = json.dumps({"model": req.model, "prompt": req.prompt}).encode("utf-8")
        request = urllib.request.Request(url, data=body, headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as resp:
                retry_after = resp.headers.get("Retry-After")
                try:
                    payload = json.loads(resp.read().decode("utf-8") or "{}")
                except ValueError:
                    payload = {}
                return {"endpoint": endpoint, "status": resp.status,
                        "payload": payload, "retry_after": retry_after}
        except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
            # urllib lives under urllib.request but raises urllib.error.HTTPError
            import urllib.error as _uerr

            retry_after: float | None = None
            if isinstance(exc, _uerr.HTTPError):
                raw = exc.headers.get("Retry-After") if exc.headers else None
                try:
                    retry_after = float(raw) if raw else None
                except (TypeError, ValueError):
                    retry_after = None
                raise GatewayError(f"zen http {exc.code} at {endpoint}",
                                   status_code=exc.code,
                                   retry_after_s=retry_after) from exc
            raise GatewayError(str(exc)) from exc
        except OSError as exc:
            raise GatewayError(f"zen transport error at {endpoint}: {exc}") from exc

    async def asend(self, model: str, prompt: str) -> dict:
        async with self._alock:
            with self._lock:
                if self._in_flight >= self.max_in_flight:
                    raise GatewayError("dispatch serialized: gateway busy")
                self._in_flight += 1
            try:
                req = ZenRequest(model=model, prompt=prompt)
                last: GatewayError | None = None
                for endpoint in self.endpoints:  # endpoint-aware failover
                    try:
                        return await asyncio.to_thread(self._post, endpoint, req)
                    except GatewayError as exc:
                        last = exc
                        # Fail over on server errors / rate limits; abort on auth.
                        if exc.status_code == 401:
                            break
                        continue
                raise last or GatewayError("all zen endpoints failed")
            finally:
                with self._lock:
                    self._in_flight -= 1
