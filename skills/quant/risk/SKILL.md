---
name: quant/risk
description: >-
  Volatility forecasting (GARCH) + Kelly position sizing with guardrails.
  Input: returns, win rate, payoff. Output: size fraction, TP/SL multipliers.
---

# quant/risk

Forecast how wild tomorrow is, then bet a fraction of what the math allows —
never the full Kelly.

## Trigger

Use when: sizing any position, scaling exits to forecast volatility, or an
agent proposes leverage without a sizing model.

## GARCHVolForecast (exact upstream API)

```python
from quant_models.garch_vol import GARCHVolForecast

g = GARCHVolForecast(p=1, q=1).fit(returns)  # log returns, 1k+ bars
fwd = g.forecast(steps=6)        # np.ndarray of forecast variances
mean = g.forecast_mean(steps=6)  # scalar mean forecast
ratio = g.vol_ratio(steps=6)     # forecast vs recent realized (>1 = heating up)
ts = g.tp_sl_multiplier(steps=6) # {'tp': x, 'sl': y} volatility-scaled
```

Rule: `vol_ratio > 1.3` → halve size or stand aside; forecasted vol, not past
vol, sizes the trade.

## KellyPositionSizer (exact upstream API)

```python
from quant_models.kelly_sizing import KellyPositionSizer

sizer = KellyPositionSizer(...)   # win-rate / payoff params + capital
sizer.set_capital(capital)
f = sizer.compute_kelly_pct()     # full Kelly fraction — NEVER trade this
size = sizer.compute_size(...)    # guarded (fractional-Kelly) size
sizer.record_outcome(was_win)     # update running stats after each trade
sizer.update_stats(...)
```

Rules (non-negotiable): trade **fractional Kelly (≤ 0.5×, 0.25× preferred)**;
recompute after every N trades, not once; `record_outcome` on EVERY closed
trade or the stats rot and the fraction lies.

## ATR stop discipline (pairs with both)

Stops at 0.7× ATR% from entry (see `quant/backtesting` ladder). A stop is a
function of current volatility, never a fixed percent.

## Verify before use

- [ ] Kelly inputs (win rate, avg win/loss) from out-of-sample trades.
- [ ] Fractional cap enforced in code, not just docs.
- [ ] GARCH fit converges (no NaN forecasts); fallback to realized vol.

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`quant_models/garch_vol.py`, `quant_models/kelly_sizing.py` (APIs verbatim).
Commit `f6d0beb`.
