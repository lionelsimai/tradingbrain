#!/usr/bin/env python3
"""Earnings calendar ingest — Finnhub /calendar/earnings.

Fetches the earnings calendar for the next/prev N days and writes a
flat parquet at `data/earnings_calendar.parquet` for use by the swing
setup blackout filter.

Schema: ticker, report_date (ISO YYYY-MM-DD), hour ('bmo'|'amc'|''),
        eps_estimate, eps_actual, revenue_estimate, revenue_actual.

Usage:
  python3 -m scripts.ingest.earnings_calendar             # default ±14d
  python3 -m scripts.ingest.earnings_calendar --back 30 --fwd 30
"""
from __future__ import annotations
import argparse, os, sys, time
from datetime import date, timedelta
from pathlib import Path
import requests, pandas as pd

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
OUT = ROOT / "data" / "earnings_calendar.parquet"
BASE = "https://finnhub.io/api/v1"


def _key() -> str | None:
    for name in ("FINNHUB_API_KEY", "FINNHUB", "finnhub", "finnhub_api_key"):
        v = os.environ.get(name)
        if v:
            return v
    return None


def fetch(key: str, frm: date, to: date) -> list[dict]:
    """Finnhub returns all US earnings between from/to, no per-ticker calls."""
    out = []
    # Chunk into 30-day windows (Finnhub free tier accepts long ranges but
    # smaller chunks are safer for retries).
    cur = frm
    while cur <= to:
        chunk_end = min(cur + timedelta(days=30), to)
        try:
            r = requests.get(
                f"{BASE}/calendar/earnings",
                params={"from": cur.isoformat(), "to": chunk_end.isoformat(), "token": key},
                timeout=20,
            )
            if r.status_code == 429:
                time.sleep(2)
                r = requests.get(
                    f"{BASE}/calendar/earnings",
                    params={"from": cur.isoformat(), "to": chunk_end.isoformat(), "token": key},
                    timeout=20,
                )
            if r.status_code == 200:
                data = r.json() or {}
                out.extend(data.get("earningsCalendar", []) or [])
        except Exception as e:
            print(f"  ! fetch {cur}..{chunk_end} failed: {e}", file=sys.stderr)
        cur = chunk_end + timedelta(days=1)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--back", type=int, default=14, help="days back from today")
    ap.add_argument("--fwd", type=int, default=14, help="days forward from today")
    a = ap.parse_args()

    key = _key()
    if not key:
        print("ERROR: FINNHUB_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    today = date.today()
    frm = today - timedelta(days=a.back)
    to = today + timedelta(days=a.fwd)
    print(f"Fetching earnings calendar {frm} → {to} ...")

    raw = fetch(key, frm, to)
    if not raw:
        print("No earnings rows returned.", file=sys.stderr)
        sys.exit(2)

    df = pd.DataFrame([
        {
            "ticker": r.get("symbol"),
            "report_date": r.get("date"),
            "hour": r.get("hour", ""),
            "eps_estimate": r.get("epsEstimate"),
            "eps_actual": r.get("epsActual"),
            "revenue_estimate": r.get("revenueEstimate"),
            "revenue_actual": r.get("revenueActual"),
        }
        for r in raw if r.get("symbol") and r.get("date")
    ])
    df = df.drop_duplicates(subset=["ticker", "report_date"]).sort_values(["report_date", "ticker"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    print(f"Wrote {len(df)} rows → {OUT}")
    # Quick sanity: how many of the universe report in the next 5 trading days
    soon = df[(df["report_date"] >= today.isoformat()) &
              (df["report_date"] <= (today + timedelta(days=7)).isoformat())]
    print(f"  {len(soon)} tickers report in the next 7 calendar days")


if __name__ == "__main__":
    main()
