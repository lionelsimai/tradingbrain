#!/usr/bin/env python3
"""Macro ingest: FRED series + Treasury yield curve.

Falls back to FRED CSV downloads if no FRED_API_KEY is set.
"""
from __future__ import annotations
import argparse, io, os, sys
from datetime import date, timedelta
from pathlib import Path
import requests, yaml, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
FRED_KEY = os.environ.get("FRED_API_KEY", "").strip()


def fetch_fred_csv(series_id: str, since: date) -> pd.DataFrame:
    """No-API-key fallback: FRED publishes a CSV per series."""
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    r = requests.get(url, timeout=20, headers={"User-Agent": SOURCES["defaults"]["user_agent"]})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    # FRED column names vary: 'observation_date' (new) or 'DATE' (old)
    date_col = "observation_date" if "observation_date" in df.columns else "DATE"
    val_col = series_id if series_id in df.columns else df.columns[1]
    df = df.rename(columns={date_col: "observation_date", val_col: "value"})
    df["observation_date"] = pd.to_datetime(df["observation_date"]).dt.date
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["value"])
    df = df[df["observation_date"] >= since]
    return df[["observation_date", "value"]]


def fetch_fred_api(series_id: str, since: date) -> pd.DataFrame:
    url = "https://api.stlouisfed.org/fred/series/observations"
    params = {
        "series_id": series_id,
        "api_key": FRED_KEY,
        "file_type": "json",
        "observation_start": str(since),
    }
    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    obs = r.json().get("observations", [])
    rows = []
    for o in obs:
        if o["value"] == ".":
            continue
        try:
            rows.append({"observation_date": date.fromisoformat(o["date"]), "value": float(o["value"])})
        except Exception:
            continue
    return pd.DataFrame(rows)


# Yahoo Finance fallback map for the most useful series (no API key needed).
YAHOO_FALLBACK = {
    "DGS10":   "^TNX",      # 10Y treasury yield (in percent)
    "DGS3MO":  "^IRX",      # 13-week T-bill
    "VIXCLS":  "^VIX",      # CBOE Volatility Index
    "DEXUSEU": "EURUSD=X",  # EUR/USD spot (note: inverse of FRED's USD/EUR)
}


def fetch_yahoo(series_id: str, since: date) -> pd.DataFrame:
    import yfinance as yf
    yt = YAHOO_FALLBACK.get(series_id)
    if not yt:
        return pd.DataFrame()
    df = yf.download(yt, start=str(since), progress=False, auto_adjust=False, group_by="column")
    if df is None or df.empty:
        return pd.DataFrame()
    # Flatten MultiIndex columns (e.g. ('Close', '^TNX') -> 'Close').
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    if "Close" not in df.columns:
        return pd.DataFrame()
    out = pd.DataFrame({
        "observation_date": pd.to_datetime(df.index).date,
        "value": pd.to_numeric(df["Close"], errors="coerce"),
    }).dropna(subset=["value"])
    return out


def upsert_series(con, series_id: str, df: pd.DataFrame) -> int:
    """Insert new observations; skip dupes."""
    if df.empty:
        return 0
    rows = [(series_id, r.observation_date, float(r.value)) for r in df.itertuples(index=False)]
    con.executemany(
        "INSERT OR IGNORE INTO macro_series (series_id, observation_date, value) VALUES (?, ?, ?)",
        rows,
    )
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default=None, help="ISO date; default = 5 years ago")
    args = ap.parse_args()

    since = date.fromisoformat(args.since) if args.since else (date.today() - timedelta(days=365 * 5))
    use_api = bool(FRED_KEY)
    print(f"Macro ingest since {since} ({'FRED API' if use_api else 'Yahoo fallback (set FRED_API_KEY for full coverage)'})")

    con = kb()
    total = 0
    skipped: list[str] = []
    for s in SOURCES["tier_2_macro"]["fred"]["series"]:
        sid = s["id"]
        try:
            if use_api:
                df = fetch_fred_api(sid, since)
            else:
                df = fetch_yahoo(sid, since)
                if df.empty and sid not in YAHOO_FALLBACK:
                    skipped.append(sid)
                    continue
            n = upsert_series(con, sid, df)
            print(f"  [{sid:8s}] {s['label']:35s} +{n} obs")
            total += n
        except Exception as e:
            print(f"  [{sid:8s}] FAILED: {e}")
    con.close()
    if skipped:
        print(f"\nSkipped (need FRED API key): {', '.join(skipped)}")
    print(f"\nDone. {total} observations written.")


if __name__ == "__main__":
    main()
