#!/usr/bin/env python3
"""Ingest X (Twitter) posts collected by the daily agent via the x_search tool.

The daily agent calls x_search with curated FinTwit handles + universe tickers
and writes a JSON file to data/raw/x/<date>.json with this shape:

{
  "as_of": "2026-05-29",
  "posts": [
    {
      "ticker": "NVDA",        # optional — agent best-effort tags
      "handle": "SemiAnalysis_",
      "posted_at": "2026-05-29T01:30:00Z",
      "text": "...",
      "likes": 432,
      "retweets": 88,
      "url": "https://x.com/...",
      "sentiment": 0.6           # -1..+1, set by the agent
    },
    ...
  ]
}

This script loads that file and inserts each post as a `documents` row with
source='x:<handle>'. The x_sentiment signal then aggregates and scores them.

Usage:
  python3 -m scripts.ingest.x_posts --file data/raw/x/2026-05-29.json
  python3 -m scripts.ingest.x_posts --stdin   # read JSON from stdin
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)


def normalise_post(p: dict) -> tuple[str, dict] | None:
    text = (p.get("text") or "").strip()
    handle = (p.get("handle") or "").lstrip("@").strip()
    if not text or not handle:
        return None
    posted_at = p.get("posted_at") or datetime.now(timezone.utc).isoformat()
    url = p.get("url") or ""
    ticker = (p.get("ticker") or "").upper().strip() or None
    doc_id = hashlib.sha256(f"x|{handle}|{posted_at}|{text[:200]}".encode()).hexdigest()[:32]
    source = f"x:{handle}"
    title = text[:120] + ("…" if len(text) > 120 else "")
    meta = {
        "handle": handle,
        "posted_at": posted_at,
        "likes": int(p.get("likes") or 0),
        "retweets": int(p.get("retweets") or 0),
        "url": url,
        "sentiment": float(p.get("sentiment", 0.0)),
        "ticker": ticker,
    }
    return doc_id, {
        "doc_id": doc_id,
        "source": source,
        "source_id": url,
        "ticker": ticker,
        "title": title,
        "url": url,
        "published_at": posted_at,
        "body": text,
        "metadata": json.dumps(meta),
    }


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--stdin", action="store_true")
    a = ap.parse_args(argv)

    if a.stdin:
        payload = json.loads(sys.stdin.read())
    elif a.file:
        payload = json.loads(Path(a.file).read_text())
    else:
        ap.error("provide --file or --stdin")

    posts = payload.get("posts", [])
    con = kb()
    inserted, skipped = 0, 0
    for p in posts:
        norm = normalise_post(p)
        if not norm:
            skipped += 1
            continue
        _, row = norm
        exists = con.execute("SELECT 1 FROM documents WHERE doc_id = ?", [row["doc_id"]]).fetchone()
        if exists:
            skipped += 1
            continue
        con.execute(
            """INSERT INTO documents
               (doc_id, source, source_id, ticker, title, url, published_at, body, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [row["doc_id"], row["source"], row["source_id"], row["ticker"],
             row["title"], row["url"], row["published_at"], row["body"], row["metadata"]],
        )
        inserted += 1
    con.close()
    print(f"X posts: inserted={inserted} skipped={skipped} (of {len(posts)})")


if __name__ == "__main__":
    main()
