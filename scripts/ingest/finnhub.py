#!/usr/bin/env python3
"""Finnhub ingest — company news + insider transactions for the AI universe.

Free tier covers what we need: 60 calls/minute, US equities, company news,
basic financials, insider sentiment + transactions. Sign up:
https://finnhub.io/register   then set FINNHUB_API_KEY at /?t=settings&s=advanced

What this writes:
- `documents` rows (source='finnhub:news') with title, body summary, url
- `insider_transactions` rows from /stock/insider-transactions

Usage:
  python3 -m scripts.ingest.finnhub                     # news + insider, all universe
  python3 -m scripts.ingest.finnhub --news-only
  python3 -m scripts.ingest.finnhub --insider-only
  python3 -m scripts.ingest.finnhub --ticker NVDA
  python3 -m scripts.ingest.finnhub --hours 24          # how far back for news
"""
from __future__ import annotations
import argparse, hashlib, json, os, sys, time
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
BASE = "https://finnhub.io/api/v1"


def all_tickers() -> list[str]:
    """Return the flat ticker list from the universe config (any layout)."""
    u = UNIVERSE.get("universe") or UNIVERSE.get("categories") or {}
    out: list[str] = []
    for _cat, lst in u.items():
        if isinstance(lst, list):
            out.extend(lst)
    return sorted(set(out))


def fp(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:32]


def get(key: str, path: str, **params) -> dict | list | None:
    params["token"] = key
    try:
        r = requests.get(f"{BASE}{path}", params=params, timeout=15)
        if r.status_code == 429:
            time.sleep(2)
            r = requests.get(f"{BASE}{path}", params=params, timeout=15)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None


def _get_api_key():
    for name in ("FINNHUB_API_KEY", "FINNHUB", "finnhub", "finnhub_api_key"):
        v = os.environ.get(name)
        if v:
            return v
    return None


def ingest_news(con, key: str, tickers: list[str], hours: int) -> int:
    today = date.today()
    since = today - timedelta(days=max(1, hours // 24 + 1))
    rows = []
    for t in tickers:
        items = get(key, "/company-news", symbol=t,
                    **{"from": since.isoformat(), "to": today.isoformat()})
        if not items:
            continue
        # cap to most recent 10 per ticker so one busy day doesn't blow the budget
        for n in items[:10]:
            published_ts = n.get("datetime")
            if not published_ts:
                continue
            published_at = datetime.fromtimestamp(published_ts, tz=timezone.utc)
            doc_id = fp("finnhub:news", str(n.get("id", "")), t, n.get("headline", ""))
            rows.append((
                doc_id,
                "finnhub:news",
                str(n.get("id", "")),
                (n.get("headline") or "")[:200],
                (n.get("summary") or "")[:5000],
                n.get("url") or "",
                t,
                published_at,
                datetime.now(timezone.utc),
                json.dumps({
                    "source": n.get("source"),
                    "category": n.get("category"),
                    "image": n.get("image"),
                }),
            ))
        time.sleep(0.1)  # courtesy throttle (well under 60/min)
    if rows:
        con.executemany(
            """INSERT OR IGNORE INTO documents
               (doc_id, source, source_id, title, body, url, ticker,
                published_at, ingested_at, metadata)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def ingest_insider(con, key: str, tickers: list[str]) -> int:
    """Pull last ~30 days of Form 4 insider txns via Finnhub.

    Schema in knowledge.duckdb:
      txn_id, ticker, insider_name, insider_role, transaction_date,
      filed_date, transaction_code, shares, price_per_share, total_value,
      shares_after
    """
    today = date.today()
    since = (today - timedelta(days=30)).isoformat()
    rows = []
    for t in tickers:
        data = get(key, "/stock/insider-transactions", symbol=t, **{"from": since, "to": today.isoformat()})
        if not data:
            continue
        for tx in data.get("data", []):
            tx_date = tx.get("transactionDate") or tx.get("filingDate")
            filed = tx.get("filingDate") or tx_date
            if not tx_date:
                continue
            shares = float(tx.get("change") or 0)
            price = float(tx.get("transactionPrice") or 0)
            txn_id = fp(
                "finnhub:f4", t, tx.get("name", ""), str(tx_date),
                tx.get("transactionCode", ""), str(shares), str(price),
            )
            rows.append((
                txn_id,
                t,
                tx.get("name") or "",
                "",  # role not provided by Finnhub free
                tx_date,
                filed,
                tx.get("transactionCode") or "",
                shares,
                price,
                shares * price if shares and price else 0.0,
                float(tx.get("share") or 0),
            ))
        time.sleep(0.1)
    if rows:
        con.executemany(
            """INSERT OR IGNORE INTO insider_transactions
               (txn_id, ticker, insider_name, insider_role,
                transaction_date, filed_date, transaction_code,
                shares, price_per_share, total_value, shares_after)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            rows,
        )
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Finnhub ingest (news + insider).")
    ap.add_argument("--news-only", action="store_true")
    ap.add_argument("--insider-only", action="store_true")
    ap.add_argument("--ticker", help="Restrict to a single ticker.")
    ap.add_argument("--hours", type=int, default=24, help="News lookback window in hours.")
    args = ap.parse_args()

    key = _get_api_key()
    if not key:
        print("⚠️  FINNHUB_API_KEY not set — skipping. Add at /?t=settings&s=advanced")
        return 0

    tickers = [args.ticker.upper()] if args.ticker else all_tickers()
    con = kb()

    do_news = not args.insider_only
    do_insider = not args.news_only

    if do_news:
        n = ingest_news(con, key, tickers, args.hours)
        print(f"finnhub news:     {n:>5} rows ({len(tickers)} tickers, {args.hours}h window)")
    if do_insider:
        n = ingest_insider(con, key, tickers)
        print(f"finnhub insider:  {n:>5} rows ({len(tickers)} tickers, 30d window)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
