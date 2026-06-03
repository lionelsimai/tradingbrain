#!/usr/bin/env python3
"""Portfolio engine — single entry point the order manager calls to validate a
proposed trade against live portfolio constraints, and to load current state.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portfolio.portfolio_state import PortfolioState, Position
from portfolio import constraints, exposure


def validate_trade(symbol: str, side: str, qty: float, price: float,
                   stop: float | None, state: PortfolioState,
                   *, sector: str | None = None) -> dict:
    """Return {allowed, violations, exposure_after}. Unknown state => reject."""
    if state is None:
        return {"allowed": False, "violations": ["unknown portfolio state"], "exposure_after": {}}
    add_notional = abs(qty) * price
    add_risk = abs(qty) * (abs(price - stop) if stop else 0.0)
    violations = constraints.evaluate(symbol, side, add_notional, add_risk, state, sector=sector)
    return {
        "allowed": not violations,
        "violations": violations,
        "exposure_after": exposure.summary(state, add_symbol=symbol, add_notional=add_notional),
    }


def load_state(mode: str = "paper") -> PortfolioState | None:
    """Build PortfolioState from the paper account/positions, or None if unknown."""
    try:
        from database import schema
        con = schema.connect(read_only=True)
        acc = con.execute(
            "SELECT equity, cash, buying_power, daily_pnl, weekly_pnl, drawdown_pct "
            "FROM paper_account ORDER BY snapshot_date DESC LIMIT 1").fetchone()
        rows = con.execute(
            "SELECT ticker, entry, stop, setup FROM paper_positions WHERE status='OPEN'").fetchall()
        con.close()
    except Exception:
        return None
    if not acc:
        # fresh account from policy default
        from safety import risk_policy
        eq = float(risk_policy.get("account", "default_equity_usd", 50000))
        return PortfolioState(mode=mode, account_equity=eq, cash=eq, buying_power=eq)
    eq, cash, bp, dpnl, wpnl, dd = acc
    positions = [Position(symbol=r[0], qty=1, entry=r[1] or 0, last=r[1] or 0, stop=r[2],
                          setup=r[3]) for r in rows]
    return PortfolioState(mode=mode, account_equity=eq or 50000, cash=cash or 0,
                          buying_power=bp or 0, positions=positions,
                          daily_pnl=dpnl or 0, weekly_pnl=wpnl or 0, drawdown_pct=dd or 0)


if __name__ == "__main__":
    import json
    s = PortfolioState(account_equity=50000, cash=50000, buying_power=50000)
    print(json.dumps(validate_trade("NVDA", "buy", 47, 212.65, 206.0, s), indent=2, default=str))
