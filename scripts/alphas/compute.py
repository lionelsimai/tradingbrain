#!/usr/bin/env python3
"""Compute all WQ alphas + a Z-score-averaged composite. Store in signals.

The composite is the cross-sectional mean of the per-alpha cross-sectional
Z-scores. Average pairwise correlation between alphas ~16% so the composite
captures meaningful orthogonal alpha.
"""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
import duckdb, numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb, PRICES_DB
from alphas.library import ALPHAS

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)

def load_panel(min_history_days: int = 120) -> pd.DataFrame:
    con = duckdb.connect(str(PRICES_DB), read_only=True)
    df = con.execute(
        """SELECT date, ticker, open, high, low, close, volume
           FROM prices
           ORDER BY ticker, date"""
    ).fetchdf()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index(["date", "ticker"]).sort_index()
    return df

def compute_all(df: pd.DataFrame) -> pd.DataFrame:
    out = {}
    for name, fn in ALPHAS.items():
        try:
            s = fn(df).rename(name)
            out[name] = s
        except Exception as e:
            print(f"  [{name}] fail: {e}")
    A = pd.concat(out.values(), axis=1)
    return A

def composite(A: pd.DataFrame) -> pd.Series:
    """Cross-sectional Z then mean across alphas. Skips NaN per row."""
    by_date = A.groupby(level="date")
    Z = (A - by_date.transform("mean")) / by_date.transform("std").replace(0, np.nan)
    return Z.mean(axis=1)

def write_signals(con, today: date, comp: pd.Series, A: pd.DataFrame):
    latest = comp.dropna().reset_index()
    latest = latest[latest["date"] == latest["date"].max()].copy()
    if latest.empty:
        return 0
    latest = latest.rename(columns={0: "value"})
    latest = latest.sort_values("value", ascending=False).reset_index(drop=True)
    latest["rk"] = latest.index + 1
    asof = latest["date"].max().date()
    con.execute("DELETE FROM signals WHERE signal_date = ? AND signal_name = 'wq_composite'", [asof])
    rows = [
        (asof, r.ticker, "wq_composite", float(r.value), int(r.rk), "{}")
        for r in latest.itertuples()
    ]
    con.executemany(
        "INSERT INTO signals (signal_date, ticker, signal_name, value, rank, metadata) VALUES (?,?,?,?,?,?)",
        rows,
    )
    return len(rows)

def main():
    df = load_panel()
    print(f"Loaded panel: {df.shape[0]:,} rows · {df.index.get_level_values('ticker').nunique()} tickers")
    A = compute_all(df)
    print(f"Computed {A.shape[1]} alphas")
    comp = composite(A)
    con = kb()
    n = write_signals(con, date.today(), comp, A)
    print(f"Wrote {n} composite scores for {comp.dropna().index.get_level_values('date').max().date()}")
    # Show top 12
    latest = comp.dropna().reset_index()
    latest = latest[latest["date"] == latest["date"].max()].copy()
    latest = latest.rename(columns={0: "value"}).sort_values("value", ascending=False)
    print("\nTop 12 WQ-composite today:")
    for r in latest.head(12).itertuples():
        print(f"  {r.ticker:>6}  z={r.value:+.2f}")

if __name__ == "__main__":
    main()
