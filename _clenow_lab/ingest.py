#!/usr/bin/env python3
"""Pull daily OHLCV for the AI universe into DuckDB.

Usage:
    python3 ingest.py [--full]   # --full = re-download 2 years; default = incremental
"""
from __future__ import annotations
import argparse, sys, time, datetime as dt
from pathlib import Path
import yaml, yfinance as yf, pandas as pd, duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
DB = ROOT / "data" / "prices.duckdb"
UNI = ROOT / "config" / "universe.yaml"

def load_tickers() -> list[tuple[str, str]]:
    cfg = yaml.safe_load(UNI.read_text())
    out: list[tuple[str, str]] = []
    for t in cfg.get("regime_benchmarks", []):
        out.append((t, "benchmark"))
    for cat, tickers in cfg.get("universe", {}).items():
        for t in tickers:
            out.append((t, cat))
    return out

def init_db(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            ticker      VARCHAR NOT NULL,
            date        DATE    NOT NULL,
            open        DOUBLE,
            high        DOUBLE,
            low         DOUBLE,
            close       DOUBLE  NOT NULL,
            adj_close   DOUBLE,
            volume      BIGINT,
            PRIMARY KEY (ticker, date)
        );
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS universe (
            ticker   VARCHAR PRIMARY KEY,
            category VARCHAR NOT NULL,
            added_at TIMESTAMP DEFAULT now()
        );
    """)

def upsert_universe(con, tickers: list[tuple[str, str]]):
    con.execute("DELETE FROM universe")
    con.executemany(
        "INSERT INTO universe (ticker, category) VALUES (?, ?)",
        [(t, c) for (t, c) in tickers],
    )

def last_date(con, ticker: str) -> dt.date | None:
    row = con.execute(
        "SELECT MAX(date) FROM prices WHERE ticker = ?", [ticker]
    ).fetchone()
    return row[0] if row and row[0] else None

def fetch_one(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    df = yf.download(
        ticker, start=start.isoformat(), end=end.isoformat(),
        progress=False, auto_adjust=False, threads=False,
    )
    if df.empty:
        return df
    df.index.name = "date"
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.reset_index().rename(columns={
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Adj Close": "adj_close", "Volume": "volume",
    })
    df["ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df[["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]]

def ingest(full: bool = False):
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(DB))
    init_db(con)
    tickers = load_tickers()
    upsert_universe(con, tickers)
    today = dt.date.today()
    horizon = today - dt.timedelta(days=730)
    n_ok, n_skip, n_err, total_rows = 0, 0, 0, 0
    for i, (t, cat) in enumerate(tickers, 1):
        try:
            since = horizon if full else (last_date(con, t) or horizon)
            if since >= today:
                n_skip += 1
                continue
            start = since + dt.timedelta(days=1) if not full and since != horizon else since
            df = fetch_one(t, start, today + dt.timedelta(days=1))
            if df.empty:
                n_skip += 1
                continue
            con.executemany(
                "INSERT OR REPLACE INTO prices (ticker, date, open, high, low, close, adj_close, volume) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                df.itertuples(index=False, name=None),
            )
            n_ok += 1
            total_rows += len(df)
            print(f"  [{i:>2}/{len(tickers)}] {t:<6} {cat:<22} +{len(df):>4} rows")
        except Exception as e:
            n_err += 1
            print(f"  [{i:>2}/{len(tickers)}] {t:<6} ERROR: {e}", file=sys.stderr)
        time.sleep(0.05)
    con.close()
    print(f"\nDone. ok={n_ok} skipped={n_skip} errors={n_err} new_rows={total_rows}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="Re-download full 2yr history")
    a = ap.parse_args()
    ingest(full=a.full)
