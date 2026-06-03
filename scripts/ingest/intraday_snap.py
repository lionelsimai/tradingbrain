#!/usr/bin/env python3
"""Intraday / pre-market price snap (Level A).

Pulls the latest available trade for every ticker in the universe — including
pre-market and post-market sessions — via yfinance and writes a flat parquet
at `data/intraday_snap.parquet`:

    ticker, last_price, prev_close, change_pct, market_state, ts_utc, source

`market_state` is one of: PRE | REGULAR | POST | CLOSED (best-effort from
yfinance fast_info or inferred from US/Eastern clock).

This snap is read by `scripts.signals.swing_setup` so that swing-setup scoring
uses the latest tradeable price instead of yesterday's EOD close.

Usage:
    python3 -m scripts.ingest.intraday_snap
    python3 -m scripts.ingest.intraday_snap --tickers DELL,ARM,AMD
    python3 -m scripts.ingest.intraday_snap --max-age-minutes 30
"""
from __future__ import annotations
import argparse, sys, time, warnings
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml, pandas as pd, yfinance as yf, duckdb

warnings.filterwarnings("ignore")

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
UNI = ROOT / "config" / "universe.yaml"
PRICES = ROOT / "data" / "prices.duckdb"
OUT = ROOT / "data" / "intraday_snap.parquet"
ET = ZoneInfo("America/New_York")


def load_universe() -> list[str]:
    cfg = yaml.safe_load(UNI.read_text())
    tickers: list[str] = list(cfg.get("regime_benchmarks", []))
    for _, names in cfg.get("universe", {}).items():
        tickers.extend(names)
    # dedupe, preserve order
    seen, out = set(), []
    for t in tickers:
        if t not in seen:
            seen.add(t); out.append(t)
    return out


def infer_market_state(now_et: datetime) -> str:
    """Infer US equity market session from US/Eastern clock.
    Pre: 04:00-09:30, Regular: 09:30-16:00, Post: 16:00-20:00, else CLOSED.
    Doesn't account for half-days / holidays; sufficient for labeling."""
    if now_et.weekday() >= 5:
        return "CLOSED"
    t = now_et.time()
    from datetime import time as dtime
    if dtime(4, 0) <= t < dtime(9, 30):    return "PRE"
    if dtime(9, 30) <= t < dtime(16, 0):   return "REGULAR"
    if dtime(16, 0) <= t < dtime(20, 0):   return "POST"
    return "CLOSED"


def snap_batch(tickers: list[str]) -> pd.DataFrame:
    """Bulk-download 2 days of 1-min bars with pre/post; take last print per ticker."""
    # Bulk-load prev closes from DuckDB (single query)
    prev_close_map: dict[str, float] = {}
    try:
        con = duckdb.connect(str(PRICES), read_only=True)
        rows = con.execute("""
            SELECT ticker, close
            FROM prices p
            WHERE date = (SELECT MAX(date) FROM prices p2 WHERE p2.ticker = p.ticker)
              AND ticker = ANY(?)
        """, [tickers]).fetchall()
        prev_close_map = {t: float(c) for t, c in rows}
        con.close()
    except Exception as e:
        print(f"  ! prev_close lookup failed: {e}", file=sys.stderr)

    # yfinance's batched download is much faster than per-ticker fast_info loops.
    df = yf.download(
        tickers=" ".join(tickers),
        period="2d",
        interval="1m",
        prepost=True,
        group_by="ticker",
        progress=False,
        threads=True,
        auto_adjust=False,
    )
    rows = []
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    state = infer_market_state(now_et)

    for t in tickers:
        try:
            sub = df[t] if len(tickers) > 1 else df
            sub = sub.dropna(subset=["Close"])
            if sub.empty:
                continue
            last = sub.iloc[-1]
            last_price = float(last["Close"])
            last_ts = sub.index[-1]
            prev_close = prev_close_map.get(t)
            change_pct = ((last_price / prev_close - 1) * 100) if prev_close else None

            rows.append({
                "ticker": t,
                "last_price": last_price,
                "prev_close": prev_close,
                "change_pct": change_pct,
                "market_state": state,
                "ts_utc": last_ts.tz_convert("UTC").to_pydatetime().replace(tzinfo=None)
                          if hasattr(last_ts, "tz_convert") else last_ts.to_pydatetime(),
                "fetched_at_utc": now_utc.replace(tzinfo=None),
                "source": "yfinance:1m",
            })
        except Exception as e:
            print(f"  ! {t}: {e}", file=sys.stderr)
    return pd.DataFrame(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated override (default: full universe)")
    ap.add_argument("--max-age-minutes", type=int, default=15,
                    help="skip refetch if snap is younger than this (default 15)")
    a = ap.parse_args()

    if a.tickers:
        tickers = [t.strip().upper() for t in a.tickers.split(",") if t.strip()]
    else:
        tickers = load_universe()

    # Short-circuit if recent snap exists
    if OUT.exists() and not a.tickers:
        age = (datetime.now(timezone.utc).replace(tzinfo=None)
               - pd.read_parquet(OUT)["fetched_at_utc"].max())
        if age < timedelta(minutes=a.max_age_minutes):
            print(f"Snap is {age.total_seconds()/60:.1f} min old (< {a.max_age_minutes}); skip.")
            return 0

    now_et = datetime.now(timezone.utc).astimezone(ET)
    state = infer_market_state(now_et)
    print(f"Snapping {len(tickers)} tickers — ET {now_et:%Y-%m-%d %H:%M} ({state})")

    t0 = time.time()
    df = snap_batch(tickers)
    if df.empty:
        print("No snaps returned.", file=sys.stderr); return 1

    df.to_parquet(OUT, index=False)
    print(f"Wrote {len(df)} snaps in {time.time()-t0:.1f}s → {OUT}")
    print(f"Sample: {df[['ticker','last_price','change_pct','market_state']].head(5).to_string(index=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
