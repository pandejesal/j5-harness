# Gateway Tuning Patch — Apply to Hermes config.yaml

## Purpose
Tune Discord gateway reliability without code changes. All settings are in `C:\Users\DELL\AppData\Local\hermes\config.yaml`.

## Backup First
```powershell
Copy-Item -LiteralPath "C:\Users\DELL\AppData\Local\hermes\config.yaml" -Destination "C:\Users\DELL\AppData\Local\hermes\config.yaml.bak-$(Get-Date -Format yyyyMMdd)" -Force
```

## Changes (apply to `config.yaml`)

### 1. Discord Backoff Tuning (lines ~137-139)
**Find:**
```yaml
fallback_providers:
  - provider: opencode-zen
    model: mimo-v2.5-free
```

**Add after `fallback_providers`:**
```yaml
gateway:
  # Discord connection resilience
  discord:
    backoff_base_s: 2          # base backoff seconds (was implicit)
    backoff_factor: 2          # exponential factor (was implicit)
    backoff_max_s: 120         # cap at 2 minutes
    backoff_jitter_pct: 30     # ±30% jitter to desync reconnects
    dns_retriable: true        # treat getaddrinfo as retriable (not fatal)
    unhealthy_socket_debounce:
      failures: 3              # consecutive failures before reconnect
      window_s: 90             # within this window
```

### 2. Health-Stale Tuning
**Add under `gateway:` section:**
```yaml
  health_stale:
    enabled: true
    threshold_s: 900          # 15 min (was implicit ~5 min)
    reconnect_on_stale: true
```

## Apply
```powershell
# After editing config.yaml, reload Hermes
hermes reload
# or restart Hermes agent
```

## Verification
Check `gateway.log` for:
- `backoff: 2s -> 4s -> 8s...` (exponential with jitter)
- `dns retriable` on getaddrinfo failures
- `unhealthy socket: 3/3 in 90s -> reconnect` (not 1/2 in 60s)
- No `fatal-stale` spam

## Rollback
```powershell
Copy-Item -LiteralPath "C:\Users\DELL\AppData\Local\hermes\config.yaml.bak-*" -Destination "C:\Users\DELL\AppData\Local\hermes\config.yaml" -Force
hermes reload
```

## Notes
- OpenClaw stays DISABLED (MCP present but unproven, adds 3rd transport)
- Revisit OpenClaw only after Kilo + Antigravity round-trips >90% for 2 weeks
- These are config-only changes — no code fork, fully reversible