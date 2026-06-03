#!/usr/bin/env python3
"""AlphaVantage ingest — earnings calendar + economic indicators.

Requires ALPHAVANTAGE_API_KEY env var. Get free key at https://www.alphavantage.co/support/#api-key
"""
from __future__ import annotations
import os, sys, csv, io, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)


def main():
    key = os.environ.get("ALPHAVANTAGE_API_KEY", "").strip()
    if not key:
        print("⚠️  ALPHAVANTAGE_API_KEY not set — skipping. Add at /?t=settings&s=advanced")
        return 0
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    tickers = {t for cat, lst in universe.get("categories", {}).items() for t in lst}

    # Earnings calendar (CSV, next 3 months)
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "EARNINGS_CALENDAR", "horizon": "3month", "apikey": key},
        timeout=30,
    )
    if r.status_code != 200 or not r.text.strip().startswith("symbol"):
        print(f"alphavantage earnings: bad response ({r.status_code})")
        return 0
    reader = csv.DictReader(io.StringIO(r.text))
    rows = [row for row in reader if row.get("symbol") in tickers]

    con = kb()
    new_docs = []
    for row in rows:
        doc_id = hashlib.sha256(f"av-earn:{row['symbol']}:{row['reportDate']}".encode()).hexdigest()[:32]
        title = f"{row['symbol']} earnings {row['reportDate']} ({row.get('horizon', '')})"
        body = json.dumps(row)
        new_docs.append((
            doc_id, "alphavantage:earnings_cal", f"{row['symbol']}-{row['reportDate']}",
            title, body, "", row["symbol"],
            datetime.now(timezone.utc), datetime.now(timezone.utc), body,
        ))
    if new_docs:
        con.executemany("""INSERT OR IGNORE INTO documents
            (doc_id, source, source_id, title, body, url, ticker, published_at, ingested_at, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", new_docs)
    print(f"alphavantage earnings: {len(new_docs)} events for {len({d[6] for d in new_docs})} tickers")


if __name__ == "__main__":
    sys.exit(main() or 0)
