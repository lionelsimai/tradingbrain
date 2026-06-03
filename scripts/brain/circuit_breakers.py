#!/usr/bin/env python3
"""Circuit breakers — rules-based, LLM-independent.

Layered loss caps:
  - daily loss > 2% equity  -> halve sizing (scalar=0.5)
  - daily loss > 4% equity  -> halt new positions (scalar=0.0) for the day
  - weekly drawdown > 5%    -> defensive (scalar=0.5)
  - total drawdown > 10%    -> halt all new positions until +recovery
  - SPY HMM regime = Crash  -> halt regardless
"""
from __future__ import annotations
import json, sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # root -> safety
from db import kb
from safety import risk_policy as _rp

ROOT = Path(__file__).resolve().parents[2]
HMM = ROOT / "reports" / "hmm-regime.json"
OUT = ROOT / "reports" / "circuit-breakers.json"

START_EQUITY = float(_rp.get("account", "default_equity_usd", 50000))


def equity_today(con) -> tuple[float, float]:
    row = con.execute(
        "SELECT equity FROM paper_account ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    equity = float(row[0]) if row else START_EQUITY
    peak_row = con.execute("SELECT MAX(equity) FROM paper_account").fetchone()
    peak = float(peak_row[0]) if peak_row and peak_row[0] else START_EQUITY
    return equity, peak


def realized_today_pct(con) -> float:
    today = date.today().isoformat()
    row = con.execute(
        "SELECT COALESCE(SUM(pnl_pct), 0) FROM paper_positions WHERE status = 'CLOSED' AND closed_at = ?",
        [today],
    ).fetchone()
    return float(row[0])


def realized_week_pct(con) -> float:
    cutoff = (date.today() - timedelta(days=7)).isoformat()
    row = con.execute(
        "SELECT COALESCE(SUM(pnl_pct), 0) FROM paper_positions WHERE status = 'CLOSED' AND closed_at >= ?",
        [cutoff],
    ).fetchone()
    return float(row[0])


def main():
    con = kb()
    equity, peak = equity_today(con)
    today_pct = realized_today_pct(con)
    week_pct = realized_week_pct(con)
    total_dd_pct = (equity / peak - 1.0) * 100.0 if peak > 0 else 0.0
    regime = json.loads(HMM.read_text()).get("acted_label", "Neutral") if HMM.exists() else "Neutral"

    breakers = []
    scalar = 1.0
    if today_pct <= -4.0:
        breakers.append(f"daily loss {today_pct:.2f}% <= -4% -> HALT")
        scalar = 0.0
    elif today_pct <= -2.0:
        breakers.append(f"daily loss {today_pct:.2f}% <= -2% -> halve")
        scalar = min(scalar, 0.5)
    if total_dd_pct <= -10.0:
        breakers.append(f"total drawdown {total_dd_pct:.2f}% -> HALT")
        scalar = 0.0
    if week_pct <= -5.0:
        breakers.append(f"weekly loss {week_pct:.2f}% <= -5% -> defensive")
        scalar = min(scalar, 0.5)
    if regime == "Crash":
        breakers.append("HMM regime = Crash -> HALT")
        scalar = 0.0

    out = {
        "asof": date.today().isoformat(),
        "equity": equity,
        "peak_equity": peak,
        "today_realized_pct": today_pct,
        "week_realized_pct": week_pct,
        "total_drawdown_pct": total_dd_pct,
        "regime": regime,
        "tripped": breakers,
        "sizing_scalar": scalar,
        "reason": "; ".join(breakers) if breakers else "no breaker tripped",
    }
    OUT.write_text(json.dumps(out, indent=2))
    if breakers:
        print(f"CIRCUIT BREAKERS TRIPPED -> sizing scalar {scalar:.2f}")
        for b in breakers: print(f"  - {b}")
    else:
        print(f"All circuits clear (equity ${equity:,.0f}, peak ${peak:,.0f}, dd {total_dd_pct:.2f}%)")


if __name__ == "__main__":
    main()
