#!/usr/bin/env python3
"""Snapshot of everything the risk gate needs to reason about exposure.

PortfolioState is a plain dataclass so it can be built from a paper account, a
broker account, or a test fixture — the constraint logic never cares which.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Position:
    symbol: str
    qty: float
    entry: float
    last: float
    stop: float | None = None
    sector: str | None = None
    strategy: str | None = None
    setup: str | None = None

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.last

    @property
    def risk_dollars(self) -> float:
        if self.stop is None:
            return 0.0
        return abs(self.qty) * abs(self.entry - self.stop)


@dataclass
class PortfolioState:
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    mode: str = "paper"
    account_equity: float = 50000.0
    cash: float = 50000.0
    buying_power: float = 50000.0
    positions: list[Position] = field(default_factory=list)
    open_orders: list[dict] = field(default_factory=list)
    pending_orders: list[dict] = field(default_factory=list)
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    drawdown_pct: float = 0.0
    loss_streak: int = 0
    sector_map: dict = field(default_factory=dict)   # symbol -> sector/category

    # ---- derived ----
    def position_for(self, symbol: str) -> Position | None:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None

    @property
    def gross_exposure_pct(self) -> float:
        if self.account_equity <= 0:
            return 0.0
        return sum(p.notional for p in self.positions) / self.account_equity * 100

    @property
    def portfolio_heat_pct(self) -> float:
        if self.account_equity <= 0:
            return 0.0
        return sum(p.risk_dollars for p in self.positions) / self.account_equity * 100

    def sector_exposure_pct(self, sector: str) -> float:
        if self.account_equity <= 0:
            return 0.0
        val = sum(p.notional for p in self.positions
                  if (p.sector or self.sector_map.get(p.symbol)) == sector)
        return val / self.account_equity * 100
