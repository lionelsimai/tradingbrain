#!/usr/bin/env python3
"""Value + Quality composite signal.

Reads the latest `fundamentals` facts and produces:
  - value_score    (cheap = high score): based on P/E, P/S, P/B, FCF yield
  - quality_score  (great = high score): margins, ROE, ROA, debt
  - vq_composite   = 0.5 * value + 0.5 * quality

Writes one row per ticker per day to the `signals` table.
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402


def latest_facts() -> pd.DataFrame:
    con = kb()
    df = con.execute(
        """SELECT ticker, key, value_num
           FROM facts
           WHERE kind = 'fundamental'
             AND as_of = (SELECT MAX(as_of) FROM facts f2
                          WHERE f2.ticker = facts.ticker AND f2.key = facts.key)"""
    ).fetch_df()
    con.close()
    return df.pivot_table(index="ticker", columns="key", values="value_num", aggfunc="last")


def zscore(s: pd.Series, invert: bool = False) -> pd.Series:
    """Cross-sectional z-score, robust to NaN. invert=True for 'lower is better' metrics."""
    s = s.replace([np.inf, -np.inf], np.nan)
    mean, std = s.mean(skipna=True), s.std(skipna=True)
    if not std or np.isnan(std):
        return pd.Series(np.zeros(len(s)), index=s.index)
    z = (s - mean) / std
    if invert:
        z = -z
    return z.clip(-3, 3).fillna(0)


def score(df: pd.DataFrame) -> pd.DataFrame:
    # FCF yield = freeCashflow / marketCap
    fcf_yield = df.get("freeCashflow", pd.Series(dtype=float)) / df.get("marketCap", pd.Series(dtype=float))
    value = (
        zscore(df.get("trailingPE", pd.Series(dtype=float)), invert=True) * 0.25 +
        zscore(df.get("forwardPE",  pd.Series(dtype=float)), invert=True) * 0.20 +
        zscore(df.get("priceToSalesTrailing12Months", pd.Series(dtype=float)), invert=True) * 0.20 +
        zscore(df.get("priceToBook", pd.Series(dtype=float)), invert=True) * 0.15 +
        zscore(fcf_yield, invert=False) * 0.20
    )
    # Net cash ratio
    net_cash = (df.get("totalCash", pd.Series(dtype=float)) -
                df.get("totalDebt", pd.Series(dtype=float))) / df.get("marketCap", pd.Series(dtype=float))
    quality = (
        zscore(df.get("grossMargins", pd.Series(dtype=float))) * 0.20 +
        zscore(df.get("operatingMargins", pd.Series(dtype=float))) * 0.20 +
        zscore(df.get("returnOnEquity", pd.Series(dtype=float))) * 0.20 +
        zscore(df.get("returnOnAssets", pd.Series(dtype=float))) * 0.15 +
        zscore(df.get("debtToEquity", pd.Series(dtype=float)), invert=True) * 0.10 +
        zscore(net_cash) * 0.15
    )
    out = pd.DataFrame({
        "value_score": value,
        "quality_score": quality,
        "vq_composite": 0.5 * value + 0.5 * quality,
    }).round(3)
    return out


def store(con, sig_date: date, df: pd.DataFrame):
    rows = []
    df = df.assign(rank_=df["vq_composite"].rank(ascending=False, method="min").astype(int))
    for ticker, r in df.iterrows():
        for name in ("value_score", "quality_score", "vq_composite"):
            rows.append((sig_date, ticker, name, float(r[name]),
                         int(r["rank_"]) if name == "vq_composite" else None,
                         json.dumps({k: float(v) if pd.notna(v) else None
                                     for k, v in r.items() if k != "rank_"})))
    con.executemany(
        """INSERT OR REPLACE INTO signals
           (signal_date, ticker, signal_name, value, rank, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""", rows
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    facts = latest_facts()
    if facts.empty:
        print("No fundamentals facts found. Run scripts/ingest/fundamentals.py first.")
        return
    scored = score(facts)
    con = kb()
    store(con, date.today(), scored)
    con.close()
    out = scored.sort_values("vq_composite", ascending=False)
    print(f"\nValue + Quality composite — top {args.top}:")
    print(f"{'rank':>4}  {'ticker':<6}  {'value':>7}  {'quality':>8}  {'vq':>7}")
    for i, (t, r) in enumerate(out.head(args.top).iterrows(), 1):
        print(f"  {i:>3}  {t:<6}  {r['value_score']:>7.2f}  {r['quality_score']:>8.2f}  {r['vq_composite']:>7.2f}")


if __name__ == "__main__":
    main()
