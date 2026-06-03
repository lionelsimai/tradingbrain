#!/usr/bin/env python3
"""News & qualitative ingest: RSS feeds + per-ticker Yahoo Finance news.

Stores each article as a `documents` row. The brain queries `documents`
with a recency filter to surface context for each ticker decision.
"""
from __future__ import annotations
import argparse, hashlib, json, sys, time
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
UA = SOURCES["defaults"]["user_agent"]


def fingerprint(*parts: str) -> str:
    return hashlib.sha256("||".join(parts).encode()).hexdigest()[:32]


def all_tickers() -> list[str]:
    out = []
    for cat, tickers in UNIVERSE["universe"].items():
        out.extend(tickers)
    return out


def parse_rss(url: str, source_name: str) -> list[dict]:
    """Tiny RSS parser using stdlib only."""
    import xml.etree.ElementTree as ET
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        print(f"  [{source_name}] fetch fail: {e}")
        return []

    items = []
    # RSS 2.0
    for item in root.iter():
        tag = item.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        title = url2 = pub = summary = ""
        for sub in item:
            stag = sub.tag.split("}")[-1]
            if stag == "title" and sub.text:
                title = sub.text.strip()
            elif stag == "link":
                url2 = sub.get("href", "") or (sub.text or "").strip()
            elif stag in ("pubDate", "published", "updated") and sub.text:
                pub = sub.text.strip()
            elif stag in ("description", "summary", "content") and sub.text:
                summary = sub.text.strip()[:2000]
        if title and url2:
            items.append({"title": title, "url": url2, "published": pub, "summary": summary})
    return items


def parse_pub_date(s: str) -> datetime | None:
    """Best-effort RFC822 / ISO date parsing."""
    if not s:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def ingest_rss_feeds() -> int:
    """Pull all enabled RSS feeds across tier 3 + 4."""
    con = kb()
    count = 0
    feeds = []
    for tier in ("tier_3_qualitative", "tier_4_sentiment", "tier_5_technical_research"):
        for name, cfg in SOURCES.get(tier, {}).items():
            if not cfg.get("enabled"):
                continue
            url = cfg.get("url")
            if not url:
                continue
            feeds.append((name, url))

    for name, url in feeds:
        items = parse_rss(url, name)
        print(f"  [{name}] {len(items)} items")
        for it in items:
            doc_id = fingerprint("rss", name, it["url"])
            existing = con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
            if existing:
                continue
            pub_dt = parse_pub_date(it["published"]) or datetime.now(timezone.utc)
            con.execute(
                """INSERT INTO documents
                   (doc_id, source, source_id, ticker, title, url, published_at, body, metadata)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)""",
                [doc_id, f"rss:{name}", it["url"], it["title"], it["url"],
                 pub_dt, it["summary"], json.dumps({"feed": name})]
            )
            count += 1
    con.close()
    return count


def ingest_yahoo_news_per_ticker(tickers: list[str]) -> int:
    """Per-ticker news via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        print("yfinance not installed")
        return 0

    con = kb()
    count = 0
    for t in tickers:
        try:
            news = yf.Ticker(t).news or []
        except Exception as e:
            print(f"  [{t}] yahoo news fail: {e}")
            continue
        for n in news:
            # yfinance shape changed: items may be under 'content'
            content = n.get("content", n)
            title = content.get("title") or n.get("title", "")
            url = (content.get("clickThroughUrl") or {}).get("url") or content.get("canonicalUrl", {}).get("url") or n.get("link", "")
            if not (title and url):
                continue
            ts = content.get("pubDate") or n.get("providerPublishTime")
            if isinstance(ts, (int, float)):
                pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            elif isinstance(ts, str):
                pub_dt = parse_pub_date(ts) or datetime.now(timezone.utc)
            else:
                pub_dt = datetime.now(timezone.utc)
            doc_id = fingerprint("yahoo", t, url)
            existing = con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [doc_id]).fetchone()
            if existing:
                continue
            summary = content.get("summary", "") or content.get("description", "")
            con.execute(
                """INSERT INTO documents
                   (doc_id, source, source_id, ticker, title, url, published_at, body, metadata)
                   VALUES (?, 'yahoo_news', ?, ?, ?, ?, ?, ?, ?)""",
                [doc_id, url, t, title[:500], url, pub_dt, summary[:2000],
                 json.dumps({"ticker": t})]
            )
            count += 1
        time.sleep(0.4)
    con.close()
    return count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rss-only", action="store_true")
    ap.add_argument("--yahoo-only", action="store_true")
    ap.add_argument("--ticker", help="Limit yahoo news to one ticker")
    args = ap.parse_args()

    total = 0
    if not args.yahoo_only:
        print("Ingesting RSS feeds...")
        total += ingest_rss_feeds()
    if not args.rss_only:
        tickers = [args.ticker.upper()] if args.ticker else all_tickers()
        print(f"\nIngesting Yahoo news for {len(tickers)} tickers...")
        total += ingest_yahoo_news_per_ticker(tickers)
    print(f"\nDone. {total} new documents.")


if __name__ == "__main__":
    main()
