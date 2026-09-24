---
name: quant/regime
description: >-
  Market-regime detection: HMM detector API + higher-timeframe bias.
  Input: log returns. Output: regime id, label, profile, TP/SL multipliers.
---

# quant/regime

Trade WITH the regime, size AGAINST uncertainty. Two tools: a 4-state HMM
over log returns, and a higher-timeframe EMA bias gate.

## Trigger

Use when: gating entries on market state, scaling TP/SL by chop vs trend, or
an agent must explain *why today is different* before sizing up.

## HMMRegimeDetector (exact upstream API)

```python
from quant_models.hmm_regime import HMMRegimeDetector

hmm = HMMRegimeDetector(n_regimes=4, n_iter=100)  # source default is (2, 200)
hmm.fit(rets)                      # rets = np.diff(np.log(close));-Series also fine
state = hmm.predict(rets[i-50:i])  # int regime id for a trailing window
proba = hmm.predict_proba(rets[i-50:i])
label = hmm.regime_label(state)    # human label, e.g. trend/chop
p = hmm.profile(state)             # {'label', 'mean', 'std', ...} per regime
mult = hmm.antitrend_multiplier(state)   # fade strength in chop
ts = hmm.dynamic_tp_sl_mult(state)       # {'tp': x, 'sl': y} regime-aware
```

Notes: fit on ≥ a few thousand 5m returns; refit periodically (regimes drift);
`random_state=42` default keeps fits reproducible.

## Higher-timeframe bias gate (cheap, no model)

```python
ema50 = close_1h.ewm(span=50, adjust=False).mean().iloc[-1]
ratio = (price - ema50) / ema50 * 100
bias = "BULLISH" if ratio > 0.5 else ("BEARISH" if ratio < -0.5 else "NEUTRAL")
```

Rule: no counter-bias entries — longs need bias ≠ BEARISH, shorts need bias ≠
BULLISH. Costs one EMA; kills a large share of chop losses.

## Verify before use

- [ ] HMM fit on in-sample only; labels from a HELD-OUT window.
- [ ] `profile()` means/stds sane (chop ≈ 0 mean + high std).
- [ ] Bias gate evaluated on CLOSED higher-timeframe bars (no intra-bar peek).

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`quant_models/hmm_regime.py` (API above is verbatim), `_debug_quant.py`
(HTF bias pattern). Commit `f6d0beb`.
