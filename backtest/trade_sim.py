#!/usr/bin/env python3
"""Single source of truth for a TradingBrain trade plan + forward simulation.

WHY THIS EXISTS
---------------
The repo grew FOUR independent definitions of "how a setup is planned and
exited":

  * scripts/analyze.py        — structural 2-target scale-out (live engine)
  * backtest/stress_test.py   — its own structural 2-target sim  -> calibration.json
  * backtest/research_engine  — yet another stop/target + scale  -> research-report.json
  * loops/signal_tracker.py   — the detector's own single target, exit-all-at-T1
                                -> live-scorecard.json

Because the live scorecard and the calibration backtest use DIFFERENT exit
rules, the "drift" the reconcile loop reads is partly an exit-rule artifact,
NOT live edge decay. Empirically, the same VCP signals score ~-0.02R under the
single-target exit and ~+0.37R under the scale-out exit over the same window.

This module gives every engine ONE plan builder and ONE bar-by-bar exit so
calibration, research, replay, and live all measure the same thing. Wire it in,
re-run the weekly retrain, and drift becomes meaningful again.

Conventions
-----------
* 1R = entry - stop (long). All returns are R-multiples, net of `costs_R`.
* `build_plan` is structural: ATR-buffered swing-low stop + two real targets.
* `simulate` walks forward up to `timeout` bars, scaling 50% at T1 and moving
  the remainder to breakeven (the doctrine's documented management plan).
* `costs_R` is round-trip cost expressed as a fraction of 1R (see costs_to_R).
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd


@dataclass
class Plan:
    entry: float
    stop: float
    t1: float
    t2: float

    @property
    def risk(self) -> float:
        return self.entry - self.stop


def atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float((df["high"] - df["low"]).tail(period).mean())
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    return float(pd.Series(tr).tail(period).mean())


def build_plan(slice_df: pd.DataFrame, atr14: float | None = None,
               last: float | None = None) -> Plan:
    """Structural plan identical to the live engine (scripts/analyze.py).

    `slice_df` must contain only bars up to and including the decision bar
    (no look-ahead). `last` lets a caller pass an intraday snap price.
    """
    a = atr14 if atr14 is not None else atr(slice_df)
    px = float(last) if last is not None else float(slice_df["close"].iloc[-1])
    return plan_from_levels(
        px, a,
        swing_low_10=float(slice_df["low"].tail(10).min()),
        swing_high_20=float(slice_df["high"].tail(20).max()),
        swing_high_60=float(slice_df["high"].tail(60).max()),
        swing_low_20=float(slice_df["low"].tail(20).min()),
        hi252=float(slice_df["high"].tail(252).max()) if len(slice_df) >= 252
        else float(slice_df["high"].tail(60).max()),
    )


def plan_from_levels(px: float, atr14: float, swing_low_10: float, swing_high_20: float,
                     swing_high_60: float, swing_low_20: float, hi252: float) -> Plan:
    """Structural plan from precomputed levels (O(1)) — single source of truth.

    Used by build_plan (live) and by backtests that precompute rolling levels.
    """
    a = atr14
    stop = max(swing_low_10 - 0.25 * a, px - 2.5 * a)
    if px < swing_high_20 * 0.995:
        t1 = swing_high_20
    elif px < hi252 * 0.995:
        t1 = hi252
    else:
        t1 = px + 2.0 * a
    base_range = swing_high_60 - swing_low_20
    t2 = max(hi252, px + 0.6 * base_range, t1 + 1.5 * a)
    if t1 <= px:
        t1 = px + 1.0 * a
    if t2 <= t1:
        t2 = t1 + 1.5 * a
    return Plan(entry=px, stop=stop, t1=t1, t2=t2)


from backtest import costs as _costs  # FIX-14: real stop-width transaction costs


def plan_costs_R(plan: "Plan", model=None) -> float:
    """Round-trip cost as a fraction of 1R, from the plan's REAL stop width
    (FIX-14). The flat costs_to_R(risk_frac_of_price=0.06) assumed every stop was
    ~6% of price, so tight-stop trades looked far cheaper than they really are."""
    return (model or _costs.BASE).cost_in_R(plan.entry, plan.stop)


def simulate(fwd: pd.DataFrame, plan: Plan, timeout: int = 20,
             costs_R: float | None = None, scale_out: bool = True,
             cost_model=None) -> dict:
    """Walk `fwd` (bars strictly after the decision bar) to stop/target/timeout.

    scale_out=True  -> book 50% at T1, move remainder to breakeven, run to T2.
    scale_out=False -> single target: exit the whole position at T1.
    Stops are checked before targets within a bar (conservative).
    Returns {r, hold, exit}.
    """
    risk = plan.risk
    if risk <= 0:
        return {"r": 0.0, "hold": 0, "exit": "invalid"}
    if costs_R is None:                       # FIX-14: real per-plan cost, not flat 0.06
        costs_R = plan_costs_R(plan, cost_model)
    n = min(timeout, len(fwd))
    half = False
    cur_stop = plan.stop
    for i in range(n):
        hi = float(fwd["high"].iloc[i])
        lo = float(fwd["low"].iloc[i])
        if lo <= cur_stop:
            if scale_out and half:
                r = 0.5 * (plan.t1 - plan.entry) / risk + 0.5 * (cur_stop - plan.entry) / risk
                return {"r": r - costs_R, "hold": i + 1, "exit": "stop_after_t1"}
            return {"r": (cur_stop - plan.entry) / risk - costs_R, "hold": i + 1, "exit": "stop"}
        if hi >= plan.t1:
            if not scale_out:
                return {"r": (plan.t1 - plan.entry) / risk - costs_R, "hold": i + 1, "exit": "t1"}
            if not half:
                half = True
                cur_stop = plan.entry  # breakeven on the runner
            if hi >= plan.t2:
                r = 0.5 * (plan.t1 - plan.entry) / risk + 0.5 * (plan.t2 - plan.entry) / risk
                return {"r": r - costs_R, "hold": i + 1, "exit": "t2"}
            continue
    last = float(fwd["close"].iloc[n - 1])
    if scale_out and half:
        r = 0.5 * (plan.t1 - plan.entry) / risk + 0.5 * (last - plan.entry) / risk
        return {"r": r - costs_R, "hold": n, "exit": "timeout_after_t1"}
    return {"r": (last - plan.entry) / risk - costs_R, "hold": n, "exit": "timeout"}


def costs_to_R(commission_bps: float, slippage_bps: float, spread_bps: float,
               risk_frac_of_price: float = 0.06) -> float:
    """Round-trip cost as a fraction of 1R — FIXED-ASSUMPTION version.

    DEPRECATED for per-trade use (FIX-14): it assumes initial risk ~= 6% of price,
    so tight-stop trades look far cheaper than they are. Prefer plan_costs_R(plan),
    which uses the REAL stop width |entry - stop|. Kept only for a uniform
    portfolio-level constant where a single number is genuinely wanted.
    """
    bps = (commission_bps + slippage_bps + spread_bps) * 2
    return (bps / 10000.0) / max(risk_frac_of_price, 1e-6)
