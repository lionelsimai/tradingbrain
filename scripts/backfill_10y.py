#!/usr/bin/env python3
"""Backfill ~10 years of daily OHLCV for the full universe (stocks + crypto + benchmarks).

Writes into prices.duckdb (PRIMARY KEY ticker+date → idempotent upserts).
Crypto uses Yahoo -USD symbols (7 day/week). Names that IPO'd recently just
get whatever history exists. Robust to partial failures; logs per-ticker.
"""
from __future__ import annotations
import time, datetime as dt
from pathlib import Path
import yaml, yfinance as yf, pandas as pd, duckdb
import argparse

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
DB = ROOT / "data" / "prices.duckdb"
UNI = ROOT / "config" / "universe.yaml"
YEARS = 10

def load_tickers():
    cfg = yaml.safe_load(UNI.read_text())
    out = []
    for t in cfg.get("regime_benchmarks", []) or cfg.get("regime", {}).get("benchmarks", []):
        out.append((t, "benchmark"))
    for cat, tickers in cfg.get("universe", {}).items():
        for t in tickers:
            out.append((t, cat))
    # dedupe preserving order
    seen = set(); uniq = []
    for t, c in out:
        if t not in seen:
            seen.add(t); uniq.append((t, c))
    return uniq

def init_db(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            ticker VARCHAR NOT NULL, date DATE NOT NULL,
            open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE NOT NULL,
            adj_close DOUBLE, volume BIGINT, PRIMARY KEY (ticker, date)
        );""")

def fetch(ticker, start, end):
    df = yf.download(ticker, start=start.isoformat(), end=end.isoformat(),
                     progress=False, auto_adjust=False, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    df.index.name = "date"
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.reset_index().rename(columns={
        "Open":"open","High":"high","Low":"low","Close":"close",
        "Adj Close":"adj_close","Volume":"volume"})
    df["ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"]).dt.date
    for col in ["open","high","low","close","adj_close","volume"]:
        if col not in df.columns: df[col] = None
    df = df[["ticker","date","open","high","low","close","adj_close","volume"]]
    df.columns.name = None
    df["ticker"] = df["ticker"].astype("object")
    return df

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--years", type=int, default=30)
    args = ap.parse_args()
    years = args.years
    end = dt.date.today() + dt.timedelta(days=1)
    start = dt.date.today() - dt.timedelta(days=years*365 + 10)
    tickers = load_tickers()
    print(f"Backfilling {len(tickers)} tickers, {start} → {end}", flush=True)
    con = duckdb.connect(str(DB))
    init_db(con)
    ok = fail = 0; total_rows = 0
    for i, (t, cat) in enumerate(tickers, 1):
        try:
            df = fetch(t, start, end)
            if df.empty:
                print(f"  [{i}/{len(tickers)}] {t}: NO DATA", flush=True); fail += 1; continue
            con.register("tmp_df", df)
            con.execute("""INSERT OR REPLACE INTO prices
                (ticker,date,open,high,low,close,adj_close,volume)
                SELECT ticker,date,open,high,low,close,adj_close,volume FROM tmp_df""")
            con.unregister("tmp_df")
            yrs = (df["date"].max() - df["date"].min()).days / 365.0
            print(f"  [{i}/{len(tickers)}] {t}: {len(df)} bars, {yrs:.1f}y ({df['date'].min()}→{df['date'].max()})", flush=True)
            ok += 1; total_rows += len(df)
        except Exception as e:
            print(f"  [{i}/{len(tickers)}] {t}: ERROR {e}", flush=True); fail += 1
        time.sleep(0.4)
    con.close()
    print(f"\nDone. ok={ok} fail={fail} total_rows={total_rows}", flush=True)

if __name__ == "__main__":
    main()
