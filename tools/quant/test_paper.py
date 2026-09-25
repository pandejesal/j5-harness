"""Unit tests for the paper-trading execution sandbox (mocked prices only).

No exchange, no network, no real money: prices are literals, persistence
uses temp dirs. Adapted alongside tools/quant/paper.py from the owner's
paper-trader repo (MIT).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.quant.paper import PaperConfig, PaperPortfolio


def _cfg(**over):
    params = {"initial_capital": 10000.0, "cash_reserve_pct": 0.05,
              "order_size_pct": 0.10, "max_position_pct": 0.25}
    params.update(over)
    return PaperConfig(**params)


class BuyTest(unittest.TestCase):
    def test_buy_sizes_within_guards(self):
        pf = PaperPortfolio(config=_cfg())
        t = pf.buy("BTC", 50000.0, reason="test", fractional=True)
        self.assertIsNotNone(t)
        # usable = 10000-500=9500; order = min(950, 2500) = 950 -> 0.019 BTC
        self.assertAlmostEqual(t["shares"], 0.019)
        self.assertLess(pf.cash, 10000.0)
        self.assertEqual(t["side"], "BUY")

    def test_buy_rejects_insufficient_funds(self):
        pf = PaperPortfolio(config=_cfg())
        # Whole-share stock: $950 order can't buy 1 share at $500k.
        self.assertIsNone(pf.buy("AAPL", 500000.0, fractional=False))
        # Tiny capital: $9.50 order below the $10 crypto minimum.
        pf2 = PaperPortfolio(config=_cfg(initial_capital=100.0))
        self.assertIsNone(pf2.buy("BTC", 50000.0, fractional=True))

    def test_avg_cost_updates(self):
        pf = PaperPortfolio(config=_cfg())
        pf.buy("BTC", 50000.0, fractional=True)
        pf.buy("BTC", 60000.0, fractional=True)
        pos = pf.positions["BTC"]
        self.assertGreater(pos["shares"], 0)
        self.assertGreater(pos["avg_cost"], 50000.0)
        self.assertLess(pos["avg_cost"], 60000.0)

    def test_integer_shares_for_stocks(self):
        pf = PaperPortfolio(config=_cfg())
        t = pf.buy("AAPL", 200.0, fractional=False)
        self.assertIsNotNone(t)
        self.assertEqual(t["shares"], int(t["shares"]))


class SellTest(unittest.TestCase):
    def test_sell_realises_pnl(self):
        pf = PaperPortfolio(config=_cfg())
        pf.buy("BTC", 50000.0, fractional=True)
        t = pf.sell("BTC", 60000.0, reason="take profit")
        self.assertIsNotNone(t)
        self.assertGreater(t["pnl"], 0)
        self.assertNotIn("BTC", pf.positions)

    def test_sell_without_position_returns_none(self):
        pf = PaperPortfolio(config=_cfg())
        self.assertIsNone(pf.sell("BTC", 60000.0))

    def test_close_all(self):
        pf = PaperPortfolio(config=_cfg())
        pf.buy("BTC", 50000.0, fractional=True)
        pf.buy("ETH", 3000.0, fractional=True)
        n = pf.close_all({"BTC": 51000.0, "ETH": 3100.0})
        self.assertEqual(n, 2)
        self.assertEqual(pf.positions, {})


class MetricsTest(unittest.TestCase):
    def test_value_pnl_allocation(self):
        pf = PaperPortfolio(config=_cfg())
        pf.buy("BTC", 50000.0, fractional=True)
        prices = {"BTC": 55000.0}
        self.assertGreater(pf.value(prices), 10000.0)
        self.assertGreater(pf.total_open_pnl(prices), 0)
        self.assertGreater(pf.return_pct(prices), 0)
        alloc = pf.allocation(prices)
        self.assertIn("cash", alloc)
        self.assertIn("BTC", alloc)
        self.assertAlmostEqual(sum(alloc.values()), 100.0, delta=0.2)

    def test_empty_portfolio(self):
        pf = PaperPortfolio(config=_cfg())
        self.assertEqual(pf.value({}), 10000.0)
        self.assertEqual(pf.total_open_pnl({}), 0.0)
        self.assertEqual(pf.total_realised_pnl(), 0)


class PersistenceTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "portfolio.json"
            pf = PaperPortfolio(config=_cfg())
            pf.buy("BTC", 50000.0, reason="round trip", fractional=True)
            pf.save(path)
            self.assertTrue(path.exists())
            pf2 = PaperPortfolio.load(path, _cfg())
            self.assertEqual(pf2.cash, pf.cash)
            self.assertEqual(pf2.positions, pf.positions)
            self.assertEqual(len(pf2.trades), 1)

    def test_load_missing_returns_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            pf = PaperPortfolio.load(Path(tmp) / "nope.json", _cfg())
            self.assertEqual(pf.cash, 10000.0)
            self.assertEqual(pf.positions, {})


if __name__ == "__main__":
    unittest.main()
