"""Paper-trading execution sandbox for quant agents.

Lets strategies trade against an auditable JSON portfolio — no real money,
no exchange keys, fully deterministic given prices. The risk-manager agent
governs against this portfolio; backtests settle fills through it.

Adapted from evsphereofficial/paper-trader (owner's MIT repo): portfolio
shape, avg-cost accounting, and guard rails (cash reserve, order-size cap,
max-position cap, minimums) are lifted verbatim in spirit; the module-level
config import is replaced with constructor injection, and persistence takes
an explicit path (no hidden state files).

Stdlib only.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("j5.paper")


@dataclass
class PaperConfig:
    """Guard rails. All fractions are of equity unless noted."""

    initial_capital: float = 100000.0
    cash_reserve_pct: float = 0.05   # cash never touched by buys
    order_size_pct: float = 0.10     # per-order cap as fraction of usable cash
    max_position_pct: float = 0.25   # per-ticker cap as fraction of capital
    crypto_min_cost: float = 10.0    # minimum notional for fractional assets


@dataclass
class PaperPortfolio:
    """In-memory portfolio with explicit JSON persistence."""

    config: PaperConfig = field(default_factory=PaperConfig)
    cash: float = 0.0
    positions: dict = field(default_factory=dict)  # ticker -> {shares, avg_cost}
    trades: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.cash:
            self.cash = round(self.config.initial_capital, 2)
        now = datetime.now().isoformat(timespec="seconds")
        self.created_at = self.created_at or now
        self.updated_at = now

    # -- metrics ------------------------------------------------------
    def value(self, prices: dict[str, float]) -> float:
        total = self.cash
        for ticker, pos in self.positions.items():
            px = prices.get(ticker)
            if px is not None:
                total += pos["shares"] * px
        return round(total, 2)

    def open_pnl(self, ticker: str, prices: dict[str, float]) -> float:
        pos = self.positions.get(ticker)
        if not pos or pos["shares"] == 0:
            return 0.0
        px = prices.get(ticker, 0)
        return round(pos["shares"] * px - pos["shares"] * pos["avg_cost"], 2)

    def total_open_pnl(self, prices: dict[str, float]) -> float:
        return round(sum(self.open_pnl(t, prices) for t in self.positions), 2)

    def total_realised_pnl(self) -> float:
        return round(sum(t.get("pnl", 0) for t in self.trades if t.get("pnl")), 2)

    def return_pct(self, prices: dict[str, float]) -> float:
        base = self.config.initial_capital
        return round((self.value(prices) - base) / base * 100, 2) if base else 0.0

    def allocation(self, prices: dict[str, float]) -> dict[str, float]:
        total = self.value(prices)
        if total <= 0:
            return {}
        alloc = {"cash": round(self.cash / total * 100, 1)}
        for ticker, pos in self.positions.items():
            px = prices.get(ticker, 0)
            pv = round(pos["shares"] * px, 2)
            if pv > 0:
                alloc[ticker] = round(pv / total * 100, 1)
        return alloc

    # -- execution ----------------------------------------------------
    def buy(self, ticker: str, price: float, reason: str = "",
            dollars: float | None = None, fractional: bool = True) -> dict | None:
        """Market buy with guard rails. Returns the trade dict, or None."""
        if price <= 0:
            return None
        cfg = self.config
        usable = max(0.0, self.cash - cfg.initial_capital * cfg.cash_reserve_pct)
        if usable <= 0:
            logger.info("no usable cash to buy %s", ticker)
            return None
        spend = usable * cfg.order_size_pct if dollars is None else min(dollars, usable)
        spend = min(spend, cfg.initial_capital * cfg.max_position_pct)
        min_cost = 10.0 if fractional else price
        min_cost = max(min_cost, cfg.crypto_min_cost if fractional else price)
        if spend < min_cost:
            logger.info("insufficient funds for %s at %.2f", ticker, price)
            return None
        shares = round(spend / price, 6) if fractional else int(spend // price)
        if shares <= 0:
            return None
        cost = round(shares * price, 2)
        self.cash = round(self.cash - cost, 2)
        pos = self.positions.setdefault(ticker, {"shares": 0, "avg_cost": 0.0})
        total_cost = pos["avg_cost"] * pos["shares"] + cost
        pos["shares"] += shares
        pos["avg_cost"] = round(total_cost / pos["shares"], 2) if pos["shares"] else 0
        trade = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                 "ticker": ticker, "side": "BUY", "shares": shares,
                 "price": round(price, 2), "value": cost, "pnl": 0,
                 "reason": reason}
        self.trades.append(trade)
        self.updated_at = trade["timestamp"]
        return trade

    def sell(self, ticker: str, price: float, reason: str = "") -> dict | None:
        """Sell the full position. Returns the trade dict, or None."""
        pos = self.positions.get(ticker)
        if not pos or pos["shares"] <= 0:
            return None
        proceeds = round(pos["shares"] * price, 2)
        pnl = round(proceeds - round(pos["shares"] * pos["avg_cost"], 2), 2)
        self.cash = round(self.cash + proceeds, 2)
        trade = {"timestamp": datetime.now().isoformat(timespec="seconds"),
                 "ticker": ticker, "side": "SELL", "shares": pos["shares"],
                 "price": round(price, 2), "value": proceeds, "pnl": pnl,
                 "reason": reason}
        del self.positions[ticker]
        self.trades.append(trade)
        self.updated_at = trade["timestamp"]
        return trade

    def close_all(self, prices: dict[str, float], reason: str = "Manual close") -> int:
        """Close every open position. Returns fills count."""
        n = 0
        for ticker in list(self.positions.keys()):
            px = prices.get(ticker)
            if px and self.sell(ticker, px, reason):
                n += 1
        return n

    # -- persistence (explicit path, no hidden state) ------------------
    def to_dict(self) -> dict:
        return {"cash": self.cash, "positions": self.positions, "trades": self.trades,
                "created_at": self.created_at, "updated_at": self.updated_at,
                "initial_capital": self.config.initial_capital}

    @classmethod
    def from_dict(cls, data: dict, config: PaperConfig | None = None) -> "PaperPortfolio":
        pf = cls(config=config or PaperConfig())
        pf.cash = data.get("cash", pf.cash)
        pf.positions = data.get("positions", {})
        pf.trades = data.get("trades", [])
        pf.created_at = data.get("created_at", pf.created_at)
        pf.updated_at = data.get("updated_at", pf.updated_at)
        return pf

    def save(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = datetime.now().isoformat(timespec="seconds")
        p.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return p

    @classmethod
    def load(cls, path: str | Path, config: PaperConfig | None = None) -> "PaperPortfolio":
        p = Path(path)
        if p.exists():
            return cls.from_dict(json.loads(p.read_text(encoding="utf-8")), config)
        return cls(config=config or PaperConfig())


__all__ = ["PaperConfig", "PaperPortfolio"]
