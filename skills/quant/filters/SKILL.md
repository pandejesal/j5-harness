---
name: quant/filters
description: >-
  Signal conditioning: Kalman smoothing, Hurst regime test, Bayesian model
  averaging across strategies. Input: prices/signals. Output: filtered signal.
---

# quant/filters

Raw price lies; raw signals overtrade. Three conditioners, composed in order:
smooth → classify → weight.

## Trigger

Use when: denoising a signal series, deciding trend-vs-mean-reversion
behavior, or blending several strategies into one vote.

## 1. KalmanPriceSmoother (exact upstream API)

```python
from quant_models.kalman_filter import KalmanPriceSmoother

kf = KalmanPriceSmoother(...)          # process/measurement noise params
smooth = kf.update(measurement)        # one price in, filtered price out
kf.filtered_price()                    # current state
kf.filtered_delta()                    # state velocity
div = kf.divergence_pct(current_price) # |price-state|/state*100 — stretch meter
sig = kf.kronos_divergence_signal(...) # stretch + direction composite
kf.reset(initial_price)                # regime breaks: reset, don't drag
```

Rule: entries on `divergence_pct` stretch-snaps get faded, not chased; reset
the filter on detected regime breaks (see `quant/regime`).

## 2. HurstExponent (exact upstream API)

```python
from quant_models.hurst_exponent import HurstExponent

H = HurstExponent().compute(prices, max_lag=None)
cls = HurstExponent().classify(H)            # trend / chop / mean-reverting
fade = HurstExponent().antitrend_multiplier(H)
ts = HurstExponent().tp_sl_adjustment(H)     # {'tp': x, 'sl': y}
```

Rule: H > 0.5 → trend-following entries, wide stops; H < 0.5 →
mean-reversion entries, tight take-profits; H ≈ 0.5 → reduce size — noise,
not signal.

## 3. BayesianModelAveraging (exact upstream API)

```python
from quant_models.bayesian_averaging import BayesianModelAveraging

bma = BayesianModelAveraging(half_life=20, min_weight=0.05)
bma.record_outcome(strategy_name, was_win, age=0)  # every resolved signal
w = bma.get_weight(strategy_name)
w_all = bma.get_weights(strategies)
direction, conf = bma.get_weighted_signal(strategy_signals)  # {name: (dir, w)}
print(bma.summary())
```

Rules: `min_weight` keeps explorers alive (no strategy goes to exactly zero);
`half_life` ~ last 20 outcomes — recent skill matters more than ancient glory;
`record_outcome` on EVERY signal or weights fossilize.

## Verify before use

- [ ] Kalman warmup bars discarded (early state is garbage).
- [ ] Hurst computed on ≥ 100 bars (short-window H is noise).
- [ ] BMA weights sum to 1 and respond to recent outcomes (spot-check).

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`quant_models/kalman_filter.py`, `quant_models/hurst_exponent.py`,
`quant_models/bayesian_averaging.py` (APIs verbatim). Commit `f6d0beb`.
