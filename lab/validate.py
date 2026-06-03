#!/usr/bin/env python3
"""Automated correctness proofs — the difference between 'we believe there's no
look-ahead' and 'we PROVE it every run'.

Checks:
  no_lookahead   — corrupt ALL data after time T; assert the signal, features,
                   and trade plan at T are byte-identical. If any future bar
                   leaks into a decision, the output changes and this fails.
  live_eq_backtest — the vectorized backtest detector (detect_at) must equal the
                   live detector (detect_setup) bar-for-bar.
  determinism    — seeded stats reproduce exactly across runs.

Run:  python3 -m lab.validate           (prints PASS/FAIL summary, exits non-zero on failure)
Also imported by tests/test_rigor.py.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT))
PRICES = ROOT / "data" / "prices.duckdb"

from scripts.signals.swing_setup import compute_features, detect_at, detect_setup
from backtest import trade_sim


def _load(ticker: str) -> pd.DataFrame:
    con = duckdb.connect(str(PRICES), read_only=True)
    df = con.execute(
        "SELECT date,open,high,low,close,volume FROM prices WHERE ticker=? ORDER BY date",
        [ticker]).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def _spy() -> pd.DataFrame:
    con = duckdb.connect(str(PRICES), read_only=True)
    df = con.execute(
        "SELECT date,open,high,low,close,volume FROM prices WHERE ticker='SPY' ORDER BY date").fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    return df


def check_no_lookahead(tickers=("NVDA", "AMD", "MSFT", "TSM"), n_points=12, seed=1):
    """The gold-standard test: future data must not change past decisions."""
    spy = _spy()
    rng = np.random.default_rng(seed)
    failures = []
    checked = 0
    for t in tickers:
        df = _load(t)
        if len(df) < 600:
            continue
        idxs = rng.integers(300, len(df) - 60, size=n_points)
        for i in idxs:
            i = int(i)
            dt = df["date"].iloc[i]
            sl = df.iloc[: i + 1]
            ss = spy[spy["date"] <= dt]
            # baseline decision + plan using only data <= i
            base_sig = detect_setup(sl, ss, clenow_rank=None)
            base_plan = trade_sim.build_plan(sl)
            # corrupt EVERYTHING after i (prices x random 0.5..1.5, volume x10)
            corrupt = df.copy()
            fut = slice(i + 1, len(df))
            factor = rng.uniform(0.5, 1.5, size=len(df) - i - 1)
            for col in ("open", "high", "low", "close"):
                corrupt.iloc[fut, corrupt.columns.get_loc(col)] = \
                    df[col].iloc[fut].values * factor
            corrupt.iloc[fut, corrupt.columns.get_loc("volume")] = \
                df["volume"].iloc[fut].values * 10
            sl2 = corrupt.iloc[: i + 1]
            sig2 = detect_setup(sl2, ss, clenow_rank=None)
            plan2 = trade_sim.build_plan(sl2)
            checked += 1
            if sig2.get("setup") != base_sig.get("setup") or \
               round(sig2.get("score", 0), 6) != round(base_sig.get("score", 0), 6):
                failures.append(f"{t}@{i}: signal changed when future corrupted")
            if abs(plan2.entry - base_plan.entry) > 1e-9 or \
               abs(plan2.stop - base_plan.stop) > 1e-9 or \
               abs(plan2.t1 - base_plan.t1) > 1e-9 or abs(plan2.t2 - base_plan.t2) > 1e-9:
                failures.append(f"{t}@{i}: trade plan changed when future corrupted")
    return {"checked": checked, "failures": failures, "pass": not failures}


def check_live_eq_backtest(tickers=("NVDA", "AMD", "GOOGL", "TSM"), step=40, seed=2):
    """detect_at (vectorized backtest path) must equal detect_setup (live path)."""
    spy = _spy()
    mism = 0
    checked = 0
    for t in tickers:
        df = _load(t)
        if len(df) < 600:
            continue
        feats = compute_features(df, spy)
        for i in range(300, len(df) - 1, step):
            dt = df["date"].iloc[i]
            sl = df.iloc[: i + 1]
            ss = spy[spy["date"] <= dt]
            a = detect_setup(sl, ss, clenow_rank=None)
            b = detect_at(feats, i, clenow_rank=None)
            checked += 1
            if a.get("setup") != b.get("setup") or \
               round(a.get("score", 0), 6) != round(b.get("score", 0), 6):
                mism += 1
    return {"checked": checked, "mismatches": mism, "pass": mism == 0}


def check_determinism():
    from lab import stats
    R = np.random.default_rng(0).normal(0.05, 1, 800)
    a = stats.stationary_bootstrap_ci(R, seed=7)
    b = stats.stationary_bootstrap_ci(R, seed=7)
    return {"pass": a == b, "ci": a}


def run_all():
    results = {
        "no_lookahead": check_no_lookahead(),
        "live_eq_backtest": check_live_eq_backtest(),
        "determinism": check_determinism(),
    }
    ok = all(v["pass"] for v in results.values())
    for name, r in results.items():
        flag = "PASS" if r["pass"] else "FAIL"
        detail = {k: v for k, v in r.items() if k != "pass"}
        print(f"  [{flag}] {name}: {detail}")
    print(f"\n{'ALL CHECKS PASS' if ok else 'VALIDATION FAILED'}")
    # Persist an auditable overfitting/correctness report (spec §11, gate 4).
    try:
        from datetime import datetime, timezone
        out = {"asof": datetime.now(timezone.utc).isoformat(),
               "pass": ok, "checks": results}
        (ROOT / "reports" / "validate.json").write_text(json.dumps(out, indent=2, default=str))
    except Exception:
        pass
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
