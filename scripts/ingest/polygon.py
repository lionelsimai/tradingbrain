#!/usr/bin/env python3
"""Polygon.io ingest — real-time quotes + news + options flow.

Requires POLYGON_API_KEY env var. Free tier at https://polygon.io/dashboard/signup
"""
from __future__ import annotations
import os, sys, hashlib, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)


def main():
    key = os.environ.get("POLYGON_API_KEY", "").strip()
    if not key:
        print("⚠️  POLYGON_API_KEY not set — skipping. Add at /?t=settings&s=advanced")
        return 0
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    tickers = [t for cat, lst in universe.get("categories", {}).items() for t in lst]

    con = kb()
    since = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_docs = []
    for t in tickers:
        r = requests.get(
            "https://api.polygon.io/v2/reference/news",
            params={"ticker": t, "published_utc.gte": since, "limit": 5, "apikey": key},
            timeout=10,
        )
        if r.status_code != 200:
            continue
        for n in r.json().get("results", []):
            doc_id = hashlib.sha256(f"polygon:{n['id']}".encode()).hexdigest()[:32]
            new_docs.append((
                doc_id, "polygon:news", n["id"], n.get("title", "")[:200],
                n.get("description", "")[:5000], n.get("article_url", ""), t,
                n.get("published_utc"), datetime.now(timezone.utc),
                json.dumps({"publisher": n.get("publisher", {}).get("name"), "tickers": n.get("tickers", [])}),
            ))
    if new_docs:
        con.executemany("""INSERT OR IGNORE INTO documents
            (doc_id, source, source_id, title, body, url, ticker, published_at, ingested_at, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", new_docs)
    print(f"polygon news: {len(new_docs)} new")


if __name__ == "__main__":
    sys.exit(main() or 0)
