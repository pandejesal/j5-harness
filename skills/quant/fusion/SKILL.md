---
namespace = "quant"
name = "fusion"
version = "1.0.0"
capabilities = ["decision-fusion"]
trigger_patterns = ["fuse signals", "confidence vote", "trade decision"]
applicable_agents = ["strategy-designer", "risk-manager", "quant"]
dependencies = {}
contract = { inputs = { task = { type = "str", required = true } }, outputs = { guidance = { type = "str" } } }
self_tests = [{ match = { task = 'smoke' }, not_match = { task = 123 } }]
---
# quant/fusion

One engine that composes the other quant skills into a single gated decision:
warm up → set bias → analyze → size exits → record the outcome. Feedback
closes the loop.

## Trigger

Use when: combining regime + signal + risk into one trade/no-trade call, or
an agent must produce an auditable decision trail per signal.

## QuantFusionEngine (exact upstream API/shape)

```python
from quant_models.fusion_layer import QuantFusionEngine  # + _compute_rsi/_compute_atr helpers

eng = QuantFusionEngine(...)
eng.warmup(...)                          # prime indicators/model state
eng.initialize(...)                      # bind data + config
eng.load_selector(model_path, predictor=None, samples=50)  # optional XGB gate
sel = eng.run_selector(df_5m)            # -> dict shortlist, if selector loaded
eng.set_htf_bias(ema50, current_price)   # BULLISH/BEARISH/NEUTRAL gate
result = eng.analyze(...)                # full pipeline -> decision dict
sized = eng._apply_tp_sl_kelly(result, atr_pct, hmm_label, H, ...)  # exits
eng.record_trade_outcome(strategy_name, was_win, age=0)  # closes the loop
print(eng.summary())
```

Pipeline order is load-bearing: bias gate BEFORE analysis (saves the model
call on counter-bias bars), Kelly AFTER direction (size a decided trade, never
to pick one), outcome recording ALWAYS (unrecorded trades rot every weight).

## Confidence gating (pairs with `quant/backtesting` vote)

`conf = total_weight / n_signals`; skip below 0.3. Direction needs
`|vote| > 0.15`. Weak consensus is HOLD, not a small position.

## Antitrend integration

In chop regimes (HMM label / Hurst < 0.5), fade strong extension signals with
`antitrend_multiplier` instead of chasing them — the backtests that survived
all run this branch. Trend regimes: follow with the full exit ladder.

## Verify before use

- [ ] Bias gate actually skips analysis (log skip counts).
- [ ] Every emitted decision has a recorded outcome within N bars.
- [ ] Selector (if loaded) abstains more than it picks on chop days.

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`quant_models/fusion_layer.py` (engine API verbatim),
`quant_models/sample_selector.py` (XGB gate pattern; weights file NOT
lifted). Commit `f6d0beb`.
