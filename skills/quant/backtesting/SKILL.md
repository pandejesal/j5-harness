---
namespace = "quant"
name = "backtesting"
version = "1.0.0"
capabilities = ["backtest", "validation"]
trigger_patterns = ["backtest", "walk-forward", "strategy validation", "trade simulation"]
applicable_agents = ["strategy-designer", "e2e-runner", "quant"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# quant/backtesting

How to run an honest backtest. Structure, exit ladder, and metrics below are
lifted verbatim from backtests that survived live deployment review.

## Trigger

Use when: validating any strategy before paper/live, comparing variants, or an
agent claims a strategy "works" without numbers.

## Exit ladder (ATR-relative, both sides)

Entry at `ep`, ATR% at entry `ae` (see `quant/indicators`):

| Exit | Long | Short |
|------|------|-------|
| TP   | `ep*(1+1.5*ae/100)` | `ep*(1-1.5*ae/100)` |
| SL   | `ep*(1-0.7*ae/100)` | `ep*(1+0.7*ae/100)` |
| TP1 (scale) | `ep*(1+0.5*ae/100)` | mirror |
| TP2 (scale) | `ep*(1+1.0*ae/100)` | mirror |
| Timestop | flat after N bars with no exit (8–12 typical) | same |

Check exits in order TP → SL → TP2 → TP1 per bar; invert PnL sign for shorts.

## Confidence-weighted fusion vote

Each signal votes `(direction, weight)` with `direction ∈ {+1, -1}`:

```python
tw = sum(w for _, w in signals)
vote = sum(d * w for d, w in signals) / tw
conf = tw / len(signals)
if conf < 0.3:
    continue  # no trade
if vote > 0.15:
    side = 'BUY'
elif vote < -0.15:
    side = 'SELL'
```

## Required metrics (every backtest report)

Trades, win rate, total PnL, avg win, avg loss, R:R, BUY/ SELL split,
exit-reason counts (`TP/SL/TP1/TP2/TS`), top-10 and worst-5 trades with
timestamps. A report missing exit reasons is rejected.

## Ablation discipline

Change ONE thing per experiment row (threshold, asymmetry, scale-out, RSI
band). The source repo's 14-row matrix (baseline → asym → conf → scale →
bands → combos) is the template: each row prints trades/WR/PnL/R:R/BUY%/SELL%.

## Verify before use

- [ ] No lookahead: signals at bar `i` use data `≤ i` only.
- [ ] Fees/slippage modeled or explicitly declared absent.
- [ ] Timestop present (no immortal positions).
- [ ] Ablation changes one variable per row.

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`_fusion_backtest.py`, `_hft_backtest.py`, `_fusion_experiments.py`.
Commit `f6d0beb`. Model-inference parts (Kronos/TimesFM, torch, CUDA) are
NOT lifted — only the loop structure, exit math, vote math, and metrics.
