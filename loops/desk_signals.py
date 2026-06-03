#!/usr/bin/env python3
"""Pre-compute doctrine-graded buy signals for the trading desk dashboard.

Grades the candidate pool through scripts.analyze (too slow to do live in an
API route) and writes reports/desk-signals.json — a ranked, dashboard-ready
buy list with grade, verdict, R/R, entry/stop/targets, and what's blocking
each near-miss.
"""
from __future__ import annotations
import json, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
OUT = ROOT / "reports" / "desk-signals.json"
PRICES = ROOT / "data" / "prices.duckdb"

# Candidate desk pool (US AI-trade equities). Filtered at runtime to whatever is
# actually in prices.duckdb so dead/renamed/crypto tickers are silently dropped
# instead of wasting a 60s subprocess each returning None.
CANDIDATE_POOL = ["NVDA","AMD","AVGO","TSM","ASML","MU","ARM","CLS","ANET","LRCX","KLAC",
        "AMAT","MSFT","GOOGL","ORCL","PLTR","NOW","APP","CRWD","SMCI","DELL",
        "VRT","COHR","CRDO","ALAB","MRVL","CRM","META","AMZN"]

def available_pool() -> list[str]:
    try:
        con = duckdb.connect(str(PRICES), read_only=True)
        have = {r[0] for r in con.execute("SELECT DISTINCT ticker FROM prices").fetchall()}
        con.close()
    except Exception:
        return CANDIDATE_POOL
    pool = [t for t in CANDIDATE_POOL if t in have]
    return pool or CANDIDATE_POOL

def grade(t: str) -> dict | None:
    try:
        r = subprocess.run([sys.executable, "-m", "scripts.analyze", t, "--json"],
                           cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        a = json.loads(r.stdout)
        plan = a.get("plan", {}) or {}
        ind = a.get("indicators", {}) or {}
        return {
            "ticker": a["ticker"], "price": a.get("price"), "setup": a.get("setup"),
            "grade": a.get("grade"), "verdict": a.get("verdict"),
            "rr": plan.get("blended_rr"), "entry": plan.get("entry"), "stop": plan.get("stop"),
            "t1": plan.get("t1"), "t2": plan.get("t2"), "theme": a.get("category"),
            "size": a.get("size"), "rs": ind.get("rs20_vs_spy"),
            "pct_equity": plan.get("pct_of_equity"), "shares": plan.get("shares"),
            "rsi": ind.get("rsi14"), "pct_to_high": ind.get("pct_to_52w_high"),
            "research": (a.get("calibration") or {}).get("research_verdict"),
            "oos": (a.get("calibration") or {}).get("oos_expectancy_R"),
            "note": a.get("setup_note") or "",
        }
    except Exception:
        return None

def quality_rank(s: dict):
    grade_score = {"A": 3, "B": 2, "C": 1}.get(s.get("grade"), 0)
    verdict_score = {"Long": 3, "Watchlist": 2, "Pass": 1}.get(s.get("verdict"), 0)
    rr = s.get("rr") or 0
    return (verdict_score, grade_score, rr)

def main():
    t0 = time.time()
    rows = [g for t in available_pool() if (g := grade(t))]
    rows.sort(key=quality_rank, reverse=True)
    buys = [r for r in rows if r.get("verdict") == "Long" and (r.get("rr") or 0) >= 2.0
            and r.get("grade") in ("A", "B")]
    watch = [r for r in rows if r.get("verdict") == "Watchlist"]
    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "n_graded": len(rows), "n_buys": len(buys), "n_watch": len(watch),
        "buys": buys, "watchlist": watch[:8], "ranked": rows,
        "compute_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"desk-signals: {len(rows)} graded, {len(buys)} buys, {len(watch)} watch ({out['compute_s']}s)")

if __name__ == "__main__":
    main()
