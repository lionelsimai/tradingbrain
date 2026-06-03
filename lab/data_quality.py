#!/usr/bin/env python3
"""Point-in-time price-data sanity gate. Garbage in = garbage edge. Before any
backtest is trusted, the data behind it must pass: no non-positive prices, no
OHLC inversions, no implausible single-day jumps (unadjusted split/bad print),
no long stale runs, and sane coverage.

Writes reports/data-quality.json and returns a pass/fail the pipeline gates on.

CLI: python3 -m lab.data_quality        (prints summary, exits non-zero if FAIL)
"""
from __future__ import annotations
import json
import sys
from pathlib import Path
import numpy as np
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
OUT = ROOT / "reports" / "data-quality.json"

# A daily move beyond this (in either direction), absent a real split, is suspect.
MAX_DAILY_MOVE = 0.60
MAX_STALE_RUN = 10          # consecutive identical closes => likely halted/bad feed
MIN_HISTORY = 252


def scan() -> dict:
    con = duckdb.connect(str(PRICES), read_only=True)
    tickers = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM prices ORDER BY ticker").fetchall()]
    issues, per_ticker = [], {}
    asof_max = con.execute("SELECT MAX(date) FROM prices").fetchone()[0]
    for t in tickers:
        df = con.execute(
            "SELECT date,open,high,low,close,volume FROM prices WHERE ticker=? ORDER BY date",
            [t]).fetchdf()
        n = len(df)
        prob = []
        nonpos = int((df[["open", "high", "low", "close"]] <= 0).any(axis=1).sum())
        if nonpos:
            prob.append(f"{nonpos} non-positive OHLC rows")
        inv_mask = ((df["high"] < df["low"]) |
                    (df["high"] < df["close"]) | (df["low"] > df["close"]))
        inv = int(inv_mask.sum())
        if inv:
            # magnitude of the worst breach relative to price (feed rounding vs real corruption)
            sub = df[inv_mask]
            breach = np.maximum.reduce([
                (sub["low"] - sub["high"]).clip(lower=0),
                (sub["close"] - sub["high"]).clip(lower=0),
                (sub["low"] - sub["close"]).clip(lower=0),
            ]) / sub["close"].abs().clip(lower=1e-9)
            worst = float(breach.max())
            kind = "material" if worst >= 0.005 else "benign"
            prob.append(f"{inv} OHLC-inversion rows ({kind}, worst {worst:.3%})")
        chg = df["close"].pct_change().abs()
        jumps = int((chg > MAX_DAILY_MOVE).sum())
        if jumps:
            prob.append(f"{jumps} daily moves > {MAX_DAILY_MOVE:.0%} (possible unadjusted split/bad print)")
        # stale runs
        same = (df["close"].diff() == 0).astype(int)
        run = maxrun = 0
        for v in same:
            run = run + 1 if v else 0
            maxrun = max(maxrun, run)
        if maxrun >= MAX_STALE_RUN:
            prob.append(f"stale run of {maxrun} identical closes")
        dups = int(df["date"].duplicated().sum())
        if dups:
            prob.append(f"{dups} duplicate dates")
        if n < MIN_HISTORY:
            prob.append(f"only {n} bars (<{MIN_HISTORY})")
        if prob:
            per_ticker[t] = prob
            issues.extend(f"{t}: {p}" for p in prob)
    con.close()

    # severity: hard failures (data-integrity) vs soft warnings (coverage)
    hard = [i for i in issues if ("non-positive" in i or "material" in i or "duplicate" in i)]
    return {
        "asof": str(asof_max),
        "tickers": len(tickers),
        "tickers_with_issues": len(per_ticker),
        "hard_failures": hard,
        "warnings": [i for i in issues if i not in hard],
        "per_ticker": per_ticker,
        "pass": len(hard) == 0,
    }


def main():
    r = scan()
    OUT.write_text(json.dumps(r, indent=2, default=str))
    print(f"Data quality — {r['tickers']} tickers, {r['tickers_with_issues']} with issues")
    print(f"  hard failures: {len(r['hard_failures'])} | warnings: {len(r['warnings'])}")
    for w in r["warnings"][:12]:
        print(f"    ⚠ {w}")
    for h in r["hard_failures"][:12]:
        print(f"    ✗ {h}")
    print(f"  -> {'PASS' if r['pass'] else 'FAIL'}  (wrote {OUT})")
    sys.exit(0 if r["pass"] else 1)


if __name__ == "__main__":
    main()
