#!/usr/bin/env python3
"""Exposure breakdowns — gross/net/long/short, by sector, strategy, setup, and
correlated cluster. Pure read over a PortfolioState.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portfolio import correlation


def _by(state, keyfn) -> dict:
    eq = max(state.account_equity, 1e-9)
    out: dict = {}
    for p in state.positions:
        k = keyfn(p) or "unknown"
        out[k] = out.get(k, 0.0) + p.notional / eq * 100
    return {k: round(v, 2) for k, v in out.items()}


def summary(state, *, add_symbol: str | None = None, add_notional: float = 0.0) -> dict:
    eq = max(state.account_equity, 1e-9)
    long_n = sum(p.notional for p in state.positions if p.qty > 0)
    short_n = sum(p.notional for p in state.positions if p.qty < 0)
    extra_corr = (correlation.correlated_exposure_pct(add_symbol, state)
                  + (add_notional / eq * 100) if add_symbol else 0.0)
    return {
        "gross_pct": round(state.gross_exposure_pct, 2),
        "net_pct": round((long_n - short_n) / eq * 100, 2),
        "long_pct": round(long_n / eq * 100, 2),
        "short_pct": round(short_n / eq * 100, 2),
        "heat_pct": round(state.portfolio_heat_pct, 2),
        "by_sector": _by(state, lambda p: p.sector or state.sector_map.get(p.symbol)),
        "by_strategy": _by(state, lambda p: p.strategy),
        "by_setup": _by(state, lambda p: p.setup),
        "correlated_pct_for_candidate": round(extra_corr, 2) if add_symbol else None,
    }


if __name__ == "__main__":
    import json
    from portfolio.portfolio_state import PortfolioState, Position
    s = PortfolioState(positions=[Position("NVDA", 10, 200, 212, 195, sector="ai")])
    print(json.dumps(summary(s, add_symbol="AMD", add_notional=5000), indent=2))
