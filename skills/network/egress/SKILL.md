---
namespace = "network"
name = "egress"
version = "1.0.0"
capabilities = ["egress", "proxy", "rotation"]
trigger_patterns = ["rotate IP", "429", "proxy", "egress IP", "rate limit"]
applicable_agents = ["coding", "general"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# network/egress

Free-tier buckets are per-IP. When 429s persist, a new egress IP is worth
more than another retry loop. This skill defines how J5 workers run behind
proxied egress (proxyman model) and how rotation is triggered and verified.

## Trigger

Use when: sustained 429s across all endpoints/models, operating in a
rate-limited network, isolating worker fleets per egress IP, or verifying
which IP a worker actually egresses from.

## 1. Model (adapted from proxyman)

- Named **instances**, each an isolated proxy endpoint (own ports, own
  circuit, own exit IP). Rotating one never affects the others.
- Workers opt in per dispatch via env: `HTTP_PROXY`/`HTTPS_PROXY` (plus
  lowercase variants) inherited by the worker subprocess.
- Rotation = new circuit + **verified** new IP before the instance returns
  to the pool. Unverified rotations don't count.
- `J5_PROXY=<http://host:port>` sets the process default; per-call
  `proxy_url` overrides it. No proxy configured = direct egress (default).

## 2. J5 wiring

- `OpencodeCliAdapter(proxy_url=...)` injects the four proxy env vars into
  the worker subprocess environment. The router, ledger, and fallback
  chains are untouched — egress is orthogonal to model selection.
- Per-bucket isolation: give each rate-limit bucket its own instance
  (Hermes fleet vs solo runs must not share fate).

## 3. Rotate-on-429 procedure

1. Confirm: 429s across ≥2 models/endpoints (not a single-model outage).
2. Rotate the instance (`proxyman rotate <name>` or control-port NEWNYM).
3. Verify: fetch an IP-echo endpoint through the instance; require a
   DIFFERENT IP than before. Same IP = rotation failed, retry once.
4. Unquarantine affected models (fresh bucket) and resume dispatch.
5. Log rotation event with before/after IPs (last octet masked) to the
   ledger — egress changes are audit-relevant.

## 4. Non-goals (explicit)

- No automatic rotation without operator opt-in (network identity changes
  are operator decisions).
- Worker HTTP stacks vary in proxy support — verify with a live IP-echo
  probe through the actual worker before relying on proxied dispatch.

## Verify before use

- [ ] Proxy endpoint alive (IP-echo returns an address).
- [ ] Rotation changes the echoed IP (verified, not assumed).
- [ ] No secrets in proxy URLs committed to config (use env).
- [ ] Direct-egress baseline measured first (know what you gained).

## Source

Adapted from `evsphereofficial/proxyman` (owner's repo: named-instance
model, rotation + verification discipline, per-terminal isolation).
Tor binaries and daemon management NOT lifted — bring your own proxy.
J5 side: `tools/router/cli_gateway.py` proxy env injection.
