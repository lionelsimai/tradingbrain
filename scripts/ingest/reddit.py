#!/usr/bin/env python3
"""Reddit ingest — r/investing, r/wallstreetbets, r/stocks, r/options.

Requires REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET env vars.
Set them at https://lionelsim.zo.computer/?t=settings&s=advanced
Create a Reddit app: https://www.reddit.com/prefs/apps -> 'script' type.
"""
from __future__ import annotations
import os, sys, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SUBS = ["investing", "stocks", "wallstreetbets", "options"]
UA = "TradingBrain/0.1 lionel@theaicapitol.com"


def get_token() -> str | None:
    cid = os.environ.get("REDDIT_CLIENT_ID", "").strip()
    sec = os.environ.get("REDDIT_CLIENT_SECRET", "").strip()
    if not cid or not sec:
        return None
    r = requests.post(
        "https://www.reddit.com/api/v1/access_token",
        auth=(cid, sec),
        data={"grant_type": "client_credentials"},
        headers={"User-Agent": UA},
        timeout=10,
    )
    if r.status_code == 200:
        return r.json().get("access_token")
    return None


def fetch_sub(token: str, sub: str, limit: int = 50) -> list[dict]:
    r = requests.get(
        f"https://oauth.reddit.com/r/{sub}/new",
        params={"limit": limit},
        headers={"Authorization": f"bearer {token}", "User-Agent": UA},
        timeout=10,
    )
    if r.status_code != 200:
        return []
    posts = r.json().get("data", {}).get("children", [])
    return [p["data"] for p in posts]


def main():
    token = get_token()
    if not token:
        print("⚠️  REDDIT_CLIENT_ID/SECRET not set — skipping. Add at /?t=settings&s=advanced")
        return 0
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    tickers = {t for cat, lst in universe.get("categories", {}).items() for t in lst}
    cashtags = {f"${t}": t for t in tickers}

    con = kb()
    new_rows = []
    for sub in SUBS:
        posts = fetch_sub(token, sub)
        for p in posts:
            title = p.get("title", "")
            body = p.get("selftext", "")
            text = f"{title}\n{body}"
            # Match cashtags ($NVDA) or naked tickers in title
            matched = [t for tag, t in cashtags.items() if tag in text or f" {t} " in f" {text} " or f" {t}." in text]
            if not matched:
                continue
            for t in matched:
                doc_id = hashlib.sha256(f"reddit:{p['id']}:{t}".encode()).hexdigest()[:32]
                new_rows.append((
                    doc_id, f"reddit:{sub}", p["id"], title[:200], text[:5000],
                    p.get("url", ""), t,
                    datetime.fromtimestamp(p["created_utc"], tz=timezone.utc),
                    datetime.now(timezone.utc),
                    json.dumps({"score": p.get("score"), "comments": p.get("num_comments"), "author": p.get("author")}),
                ))
        print(f"  r/{sub}: {len([r for r in new_rows if r[1] == f'reddit:{sub}'])} ticker hits")
    if not new_rows:
        print("Done. 0 new.")
        return 0
    con.executemany("""INSERT OR IGNORE INTO documents
        (doc_id, source, source_id, title, body, url, ticker, published_at, ingested_at, metadata)
        VALUES (?,?,?,?,?,?,?,?,?,?)""", new_rows)
    print(f"Done. {len(new_rows)} new docs.")


if __name__ == "__main__":
    sys.exit(main() or 0)
