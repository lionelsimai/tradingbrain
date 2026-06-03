#!/usr/bin/env python3
"""Point-in-time market-regime label from the broad index (fixes audit F9).

The signal ledger used to stamp every row with the literal string 'replay',
which made all per-regime analysis meaningless. This computes a REAL regime at a
given date from SPY, using only data on or before that date (no look-ahead), so
per-regime stats and regime-aware recall actually mean something.

Regime rules (deterministic, auditable):
  * trend from SPY vs its 200-day and 50-day SMAs,
  * a volatility overlay (20-day realized vol vs its own trailing distribution).
Labels: bull, bear, chop, high_vol_bull, high_vol_bear, crash.

CLI:
  python3 -m scripts.brain.regime_label 2020-03-16   # label one date
  python3 -m scripts.brain.regime_label --backfill    # rewrite signal_ledger.regime
"""
from __future__ import annotations
import sys
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from paths import ROOT

PRICES = ROOT / "data" / "prices.duckdb"
KB = ROOT / "data" / "knowledge.duckdb"
INDEX = "SPY"


@lru_cache(maxsize=1)
def _spy() -> pd.DataFrame:
    import duckdb
    con = duckdb.connect(str(PRICES), read_only=True)
    try:
        df = con.execute(
            "SELECT date, adj_close AS close FROM prices WHERE ticker = ? ORDER BY date",
            [INDEX]).fetchdf()
    finally:
        con.close()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date")
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    ret = df["close"].pct_change()
    df["vol20"] = ret.rolling(20).std()
    # trailing 1y median vol, as a point-in-time volatility yardstick
    df["vol_med"] = df["vol20"].rolling(252, min_periods=60).median()
    return df


def regime_at(d) -> str:
    """Regime label using only SPY data on/before date d. Returns 'unknown' if
    there isn't enough history yet."""
    if isinstance(d, str):
        d = pd.to_datetime(d)
    elif isinstance(d, (date, datetime)):
        d = pd.to_datetime(d)
    df = _spy()
    past = df[df.index <= d]
    if len(past) < 200 or pd.isna(past["sma200"].iloc[-1]):
        return "unknown"
    row = past.iloc[-1]
    close, s50, s200 = row["close"], row["sma50"], row["sma200"]
    vol, vmed = row["vol20"], row["vol_med"]
    high_vol = bool(vmed and vol and vol > 1.6 * vmed)
    crash = bool(vmed and vol and vol > 2.5 * vmed and close < s200)
    if crash:
        return "crash"
    up = close > s200 and s50 >= s200
    down = close < s200 and s50 < s200
    if up:
        return "high_vol_bull" if high_vol else "bull"
    if down:
        return "high_vol_bear" if high_vol else "bear"
    return "chop"


def backfill() -> dict:
    """Rewrite signal_ledger.regime with the real point-in-time label per emit_date."""
    import duckdb
    con = duckdb.connect(str(KB))
    rows = con.execute("SELECT id, emit_date FROM signal_ledger").fetchall()
    counts: dict[str, int] = {}
    for sid, ed in rows:
        lbl = regime_at(ed)
        counts[lbl] = counts.get(lbl, 0) + 1
        con.execute("UPDATE signal_ledger SET regime = ? WHERE id = ?", [lbl, sid])
    con.close()
    return counts


def main():
    if "--backfill" in sys.argv:
        counts = backfill()
        print("Backfilled signal_ledger.regime:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
    elif len(sys.argv) > 1:
        print(f"{sys.argv[1]} -> regime: {regime_at(sys.argv[1])}")
    else:
        today = _spy().index[-1]
        print(f"latest ({today.date()}) -> regime: {regime_at(today)}")


if __name__ == "__main__":
    main()
