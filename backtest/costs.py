#!/usr/bin/env python3
"""Shared transaction-cost model (FIX-3 / FIX-14).

The prior cost path (`backtest/trade_sim.py:142`) divided bps by a hardcoded
`risk_frac_of_price = 0.06` to express cost in R — a load-bearing, optimistic
assumption: it makes round-trip cost ~constant regardless of the REAL stop width,
so tight-stop strategies look far cheaper than they are. This module expresses
cost in R from the ACTUAL stop distance |entry - stop|, and provides honest
named presets and a conservative gap-through-stop fill.

Pure + dependency-free so it is unit-testable without the price DB.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Per-SIDE costs in basis points."""
    commission_bps: float = 1.0
    slippage_bps: float = 5.0
    half_spread_bps: float = 4.0   # half the quoted spread, paid each side

    def per_side_bps(self) -> float:
        return self.commission_bps + self.slippage_bps + self.half_spread_bps

    def round_trip_bps(self) -> float:
        return 2.0 * self.per_side_bps()

    def round_trip_cost_per_share(self, entry: float) -> float:
        """Dollar cost per share for a round trip at `entry`."""
        return float(entry) * self.round_trip_bps() / 10000.0

    def cost_in_R(self, entry: float, stop: float) -> float:
        """Round-trip cost in R (multiples of per-share risk), using the REAL
        stop width. Zero/negative stop width => infinite cost (fail-loud)."""
        risk_per_share = abs(float(entry) - float(stop))
        if risk_per_share <= 0:
            return float("inf")
        return self.round_trip_cost_per_share(entry) / risk_per_share


# Honest preset ladder (red-team §9: zero is for DIAGNOSIS ONLY).
ZERO = CostModel(0.0, 0.0, 0.0)
BASE = CostModel(commission_bps=1.0, slippage_bps=5.0, half_spread_bps=4.0)
CONSERVATIVE = CostModel(commission_bps=1.0, slippage_bps=10.0, half_spread_bps=8.0)
SEVERE = CostModel(commission_bps=2.0, slippage_bps=20.0, half_spread_bps=15.0)
CRISIS = CostModel(commission_bps=2.0, slippage_bps=40.0, half_spread_bps=30.0)

PRESETS = {"zero": ZERO, "base": BASE, "conservative": CONSERVATIVE,
           "severe": SEVERE, "crisis": CRISIS}


def gap_fill_price(side: str, stop: float, bar_open: float) -> float:
    """Conservative gap-through-stop fill: if the bar GAPS past the stop you fill
    at the (worse) open, never at the stop. (red-team §9 / FIX-3.)
      long  : gap-down open below the stop => fill at the lower open
      short : gap-up open above the stop  => fill at the higher open
    """
    s = side.lower()
    if s in ("buy", "long"):
        return min(float(stop), float(bar_open))
    return max(float(stop), float(bar_open))
