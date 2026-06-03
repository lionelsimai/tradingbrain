#!/usr/bin/env python3
"""Per-ticker fundamentals snapshot (yfinance). Powers the value+quality signal."""
from __future__ import annotations
import argparse, json, sys, time
from datetime import datetime
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
FIELDS = SOURCES["fundamentals_lookup"]["yfinance"]["fields"]


def all_tickers() -> list[str]:
    out = []
    for cat, tickers in UNIVERSE["universe"].items():
        out.extend(tickers)
    return out


def snapshot(ticker: str) -> dict:
    import yfinance as yf
    info = yf.Ticker(ticker).info or {}
    return {f: info.get(f) for f in FIELDS}


def store_facts(con, ticker: str, snap: dict):
    import hashlib
    now = datetime.utcnow()
    for k, v in snap.items():
        if v is None:
            continue
        fact_id = hashlib.sha256(f"{ticker}|{k}|{now.date()}".encode()).hexdigest()[:32]
        try:
            num = float(v) if isinstance(v, (int, float)) else None
        except Exception:
            num = None
        # doc_id is required and FK-like; we use a synthetic snapshot doc per day per ticker
        snap_doc_id = hashlib.sha256(f"fundamentals|{ticker}|{now.date()}".encode()).hexdigest()[:32]
        con.execute(
            "INSERT OR IGNORE INTO documents (doc_id, source, source_id, ticker, title, published_at, metadata) VALUES (?, 'fundamentals', ?, ?, ?, ?, ?)",
            [snap_doc_id, f"snap-{ticker}-{now.date()}", ticker,
             f"{ticker} fundamentals snapshot {now.date()}", now, json.dumps({"date": str(now.date())})]
        )
        con.execute(
            """INSERT OR REPLACE INTO facts
               (fact_id, doc_id, ticker, kind, key, value_num, value_text, as_of)
               VALUES (?, ?, ?, 'fundamental', ?, ?, ?, ?)""",
            [fact_id, snap_doc_id, ticker, k, num,
             str(v) if num is None else None, now]
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", help="One ticker")
    args = ap.parse_args()

    tickers = [args.ticker.upper()] if args.ticker else all_tickers()
    con = kb()
    n = 0
    for t in tickers:
        try:
            snap = snapshot(t)
            store_facts(con, t, snap)
            non_null = sum(1 for v in snap.values() if v is not None)
            print(f"  [{t}] {non_null}/{len(snap)} fields")
            n += non_null
            time.sleep(0.3)
        except Exception as e:
            print(f"  [{t}] FAILED: {e}")
    con.close()
    print(f"\nDone. {n} facts updated.")


if __name__ == "__main__":
    main()
