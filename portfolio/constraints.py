#!/usr/bin/env python3
"""Portfolio constraints — pure functions that return a list of violations for a
PROPOSED trade given current state + canonical policy. Empty list = allowed.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import risk_policy
from portfolio import correlation


def evaluate(symbol: str, side: str, add_notional: float, add_risk_dollars: float,
             state, *, sector: str | None = None,
             allow_pyramiding: bool | None = None) -> list[str]:
    pol = risk_policy.load()
    pr = pol["portfolio_risk"]
    tr = pol["trade_risk"]
    eq = max(state.account_equity, 1e-9)
    v: list[str] = []

    if allow_pyramiding is None:
        allow_pyramiding = bool(tr.get("allow_pyramiding", False))

    # duplicate / conflicting
    existing = state.position_for(symbol)
    if existing is not None and not allow_pyramiding:
        v.append(f"duplicate open position in {symbol} (pyramiding disabled)")
    if existing is not None and side.lower() == "buy" and existing.qty < 0:
        v.append(f"conflicting side: long proposal vs short position in {symbol}")

    # concurrent positions
    if existing is None and len(state.positions) >= int(pr["max_concurrent_positions"]):
        v.append(f"max concurrent positions {pr['max_concurrent_positions']} reached")

    # position size
    pos_pct = add_notional / eq * 100
    if pos_pct > float(tr["max_position_pct"]) + 1e-6:
        v.append(f"position {pos_pct:.1f}% > max {tr['max_position_pct']}%")

    # portfolio heat
    heat_after = state.portfolio_heat_pct + add_risk_dollars / eq * 100
    if heat_after > float(pr["max_portfolio_heat_pct"]) + 1e-6:
        v.append(f"portfolio heat {heat_after:.1f}% > max {pr['max_portfolio_heat_pct']}%")

    # sector
    sec = sector or state.sector_map.get(symbol)
    if sec:
        sec_after = state.sector_exposure_pct(sec) + pos_pct
        if sec_after > float(pr["max_sector_exposure_pct"]) + 1e-6:
            v.append(f"sector {sec} exposure {sec_after:.1f}% > max {pr['max_sector_exposure_pct']}%")

    # correlated cluster
    corr_after = correlation.correlated_exposure_pct(symbol, state) + pos_pct
    if corr_after > float(pr["max_correlated_exposure_pct"]) + 1e-6:
        v.append(f"correlated exposure {corr_after:.1f}% > max {pr['max_correlated_exposure_pct']}%")

    # cash / buying power
    if add_notional > state.cash + 1e-6:
        v.append(f"insufficient cash (${state.cash:.0f} < ${add_notional:.0f})")
    if add_notional > state.buying_power + 1e-6:
        v.append("insufficient buying power")

    # loss halts
    if abs(min(state.daily_pnl, 0)) / eq * 100 >= float(pr["max_daily_loss_pct"]):
        v.append("daily loss limit reached")
    if abs(min(state.weekly_pnl, 0)) / eq * 100 >= float(pr["max_weekly_loss_pct"]):
        v.append("weekly loss limit reached")
    if state.drawdown_pct >= float(pr["max_total_drawdown_pct"]):
        v.append("max drawdown reached")
    if state.loss_streak >= int(pr["stop_after_loss_streak"]):
        v.append(f"loss streak {state.loss_streak} >= {pr['stop_after_loss_streak']}")

    return v
