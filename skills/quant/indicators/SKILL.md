---
name: quant/indicators
description: >-
  NumPy ATR/RSI/ADX reference implementations for market data features.
  Input: OHLC arrays. Output: indicator series. Pure numpy/pandas, no network.
---

# quant/indicators

Reference indicator implementations. Copy-adapt, don't re-derive — these exact
forms are battle-tested in live backtests.

## Trigger

Use when: building features for strategies, backtests, or regime filters; any
agent needs ATR/RSI/ADX without pulling a heavy TA library.

## ATR (percent)

```python
import numpy as np

def atr_pct(h, l, c, p=14):
    tr = np.maximum(h[1:] - l[1:],
                    np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    a = np.full(len(c), 0.2)
    for i in range(p, len(c)):
        a[i] = np.mean(tr[i-p:i])
    return a / c * 100  # percent of price — regime-comparable across assets
```

## RSI (Wilder-style, percent)

```python
def rsi(c, p=14):
    if len(c) <= p:
        return np.full(len(c), 50.0)
    d = np.diff(c)
    g = np.where(d > 0, d, 0)
    l_ = np.where(d < 0, -d, 0)
    r = np.full(len(c), 50.0)
    for i in range(p, len(c)):
        ag = np.mean(g[i-p:i])
        al = np.mean(l_[i-p:i])
        r[i] = 100 - 100 / (1 + ag / al) if al else 100
    return r
```

## ADX (Wilder RMA variant — matches TradingView)

True-range / ±DM accumulated with Wilder RMA (`ewm(alpha=1/period)`), then
`DX = 100*|PDI-NDI|/(PDI+NDI)`, ADX = RMA(DX). Returns
`(adx, plus_di, minus_di)` for the last bar. Guard `tr=0` divisions with
`.replace(0, nan)` on pandas Series.

## Verify before use

- [ ] ATR output is in **percent of price**, not points.
- [ ] RSI seed is 50.0 for the first `p` bars (no lookahead).
- [ ] ADX cross-checked against a second implementation (SMA variant) on the
      same window; Wilder variant is the canonical one.

## Source

Adapted from `evsphereofficial/kronos-btc-trader` ([MIT](https://github.com/evsphereofficial/kronos-btc-trader)):
`_fusion_backtest.py` (`calc_atr`, `calc_rsi`), `_test_adx.py`
(`calc_adx_wilder`). Commit `f6d0beb`. Originals fetch live Binance data via
ccxt and need torch/GPU for model parts — only the pure-numpy indicator forms
are lifted here.
