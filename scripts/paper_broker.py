#!/usr/bin/env python3
"""Paper broker: open from setups, mark daily, close at stop/target/timeout."""
from __future__ import annotations
import json, sys, hashlib
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))         # scripts/ -> db
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))     # root -> safety, paths
from db import kb, prices
from paths import ROOT
from safety import risk_policy as _rp

SETUPS = ROOT / "reports" / "swing-setups.json"
# Sourced from the CANONICAL risk policy (config/risk_policy.yaml) — no hardcoding.
START_EQUITY = float(_rp.get("account", "default_equity_usd", 50000))
MAX_OPEN = int(_rp.get("portfolio_risk", "max_concurrent_positions", 6))
MAX_RISK_PER_TRADE = float(_rp.get("trade_risk", "risk_per_trade_pct", 0.5)) / 100.0
MAX_TOTAL_RISK = float(_rp.get("portfolio_risk", "max_portfolio_heat_pct", 4.0)) / 100.0
TIMEOUT_DAYS = 20
RULES_PATH = ROOT / "config" / "sources.yaml"

def ensure_account_seed(con):
    r = con.execute("SELECT MAX(snapshot_date) FROM paper_account").fetchone()
    if r and r[0]:
        return
    con.execute(
        "INSERT INTO paper_account VALUES (?, ?, 0, 0, 0, 0, 0)",
        [date.today() - timedelta(days=1), START_EQUITY],
    )

def current_equity(con) -> float:
    r = con.execute("SELECT equity FROM paper_account ORDER BY snapshot_date DESC LIMIT 1").fetchone()
    return float(r[0]) if r else START_EQUITY

def open_positions(con):
    return con.execute(
        "SELECT position_id, ticker, opened_at, entry, stop, target, risk_pct, size_R, meta"
        " FROM paper_positions WHERE status = 'OPEN' ORDER BY opened_at"
    ).fetchdf()

def open_count_and_risk(con) -> tuple[int, float]:
    df = open_positions(con)
    n = len(df)
    risk = float(df["risk_pct"].sum()) if n else 0.0
    return n, risk

def latest_price(pcon, ticker: str) -> tuple[date, float, float, float] | None:
    r = pcon.execute(
        "SELECT date, open, high, low, close FROM prices WHERE ticker=? ORDER BY date DESC LIMIT 1",
        [ticker]
    ).fetchone()
    return (r[0], float(r[2]), float(r[3]), float(r[4])) if r else None

def open_from_setups(con, pcon, today: date) -> int:
    if not SETUPS.exists():
        return 0
    data = json.loads(SETUPS.read_text())
    setups = data.get("candidates") if isinstance(data, dict) else data
    if not setups:
        return 0
    alloc_path = ROOT / "reports" / "allocation.json"
    scalar = 1.0
    if alloc_path.exists():
        try:
            scalar = float(json.loads(alloc_path.read_text()).get("final_sizing_scalar", 1.0))
        except Exception:
            pass
    if scalar <= 0:
        print(f"  allocation scalar = {scalar:.2f} -> halt new positions")
        return 0
    n_open, total_risk = open_count_and_risk(con)
    held = {r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM paper_positions WHERE status='OPEN'"
    ).fetchall()}
    opened = 0
    for s in setups:
        if n_open >= MAX_OPEN or total_risk >= MAX_TOTAL_RISK:
            break
        t = s["ticker"]
        if t in held:
            continue
        entry, stop, target = float(s["entry"]), float(s["stop"]), float(s["target"])
        if entry <= 0 or stop <= 0 or entry <= stop:
            continue
        risk_pct = MAX_RISK_PER_TRADE * scalar
        if total_risk + risk_pct > MAX_TOTAL_RISK:
            continue
        pid = hashlib.sha1(f"{t}-{today}-{entry}".encode()).hexdigest()[:16]
        con.execute(
            "INSERT INTO paper_positions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [pid, t, s.get("setup", "?"), today, entry, stop, target,
             risk_pct, 1.0, "OPEN", None, None, None, None,
             json.dumps({"reason": s.get("reason", ""), "r_multiple": s.get("r", s.get("r_multiple"))})],
        )
        n_open += 1
        total_risk += risk_pct
        opened += 1
        held.add(t)
    return opened

def mark_to_market(con, pcon, today: date) -> tuple[int, float, float]:
    df = open_positions(con)
    closed = 0
    realized_R = 0.0
    unrealized_R = 0.0
    for _, p in df.iterrows():
        lp = latest_price(pcon, p["ticker"])
        if not lp:
            continue
        _, hi, lo, close = lp
        entry = float(p["entry"]); stop = float(p["stop"]); tgt = float(p["target"])
        R = entry - stop
        # stop first if hit intraday
        if lo <= stop:
            exit_p = stop
            r_mult = (exit_p - entry) / R
            con.execute(
                "UPDATE paper_positions SET status='CLOSED_STOP', closed_at=?, exit=?, pnl_R=?, pnl_pct=? WHERE position_id=?",
                [today, exit_p, r_mult, (exit_p/entry - 1.0) * 100, p["position_id"]],
            )
            realized_R += r_mult; closed += 1
            continue
        if hi >= tgt:
            exit_p = tgt
            r_mult = (exit_p - entry) / R
            con.execute(
                "UPDATE paper_positions SET status='CLOSED_TARGET', closed_at=?, exit=?, pnl_R=?, pnl_pct=? WHERE position_id=?",
                [today, exit_p, r_mult, (exit_p/entry - 1.0) * 100, p["position_id"]],
            )
            realized_R += r_mult; closed += 1
            continue
        opened = p["opened_at"]
        opened_d = opened.date() if hasattr(opened, "date") else opened
        if (today - opened_d).days >= TIMEOUT_DAYS:
            r_mult = (close - entry) / R
            con.execute(
                "UPDATE paper_positions SET status='CLOSED_TIMEOUT', closed_at=?, exit=?, pnl_R=?, pnl_pct=? WHERE position_id=?",
                [today, close, r_mult, (close/entry - 1.0) * 100, p["position_id"]],
            )
            realized_R += r_mult; closed += 1
            continue
        unrealized_R += (close - entry) / R
    return closed, realized_R, unrealized_R

def snapshot(con, today: date, closed: int, realized_R: float, unrealized_R: float):
    n_open, total_risk = open_count_and_risk(con)
    prev_eq = current_equity(con)
    # 1R = 1% of prev equity
    delta = (realized_R * MAX_RISK_PER_TRADE) * prev_eq
    new_eq = prev_eq + delta
    con.execute(
        "INSERT OR REPLACE INTO paper_account VALUES (?,?,?,?,?,?,?)",
        [today, new_eq, total_risk, n_open, closed, realized_R, unrealized_R],
    )
    return new_eq, n_open, total_risk

def main():
    con = kb()
    pcon = prices()
    today = date.today()
    ensure_account_seed(con)
    opened = open_from_setups(con, pcon, today)
    closed, realized_R, unrealized_R = mark_to_market(con, pcon, today)
    eq, n_open, total_risk = snapshot(con, today, closed, realized_R, unrealized_R)
    print(f"Paper broker · {today}")
    print(f"  opened={opened}  closed={closed}  open_now={n_open}  total_risk={total_risk:.2%}")
    print(f"  realized_R={realized_R:+.2f}  unrealized_R={unrealized_R:+.2f}  equity=${eq:,.0f}")

if __name__ == "__main__":
    main()
