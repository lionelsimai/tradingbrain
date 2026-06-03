#!/usr/bin/env python3
"""Quartr ingest — earnings call transcripts + investor day events.

Requires QUARTR_API_KEY env var. Apply for access at https://quartr.com/api
Quartr's free tier is limited; full transcripts are the highest-signal
qualitative source per dollar in finance — well worth the setup.
"""
from __future__ import annotations
import os, sys, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import requests, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)


def main():
    key = os.environ.get("QUARTR_API_KEY", "").strip()
    if not key:
        print("⚠️  QUARTR_API_KEY not set — skipping. Apply at https://quartr.com/api, add key at /?t=settings&s=advanced")
        return 0
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    tickers = [t for cat, lst in universe.get("categories", {}).items() for t in lst]

    con = kb()
    headers = {"X-Api-Key": key}
    new_docs = []
    for t in tickers[:5]:  # rate-limit: 5 per run
        r = requests.get(
            f"https://api.quartr.com/v1/companies/{t}/events",
            headers=headers,
            timeout=10,
        )
        if r.status_code != 200:
            continue
        for ev in r.json().get("events", [])[:3]:
            transcript_url = ev.get("liveTranscriptUrl") or ev.get("transcriptUrl")
            if not transcript_url:
                continue
            tr = requests.get(transcript_url, headers=headers, timeout=20)
            body = tr.text[:50000] if tr.status_code == 200 else ""
            doc_id = hashlib.sha256(f"quartr:{ev['id']}".encode()).hexdigest()[:32]
            new_docs.append((
                doc_id, "quartr:transcript", str(ev["id"]),
                f"{t} {ev.get('eventType', 'event')} {ev.get('date', '')}", body,
                transcript_url, t,
                ev.get("date"), datetime.now(timezone.utc),
                json.dumps({"event_type": ev.get("eventType")}),
            ))
    if new_docs:
        con.executemany("""INSERT OR IGNORE INTO documents
            (doc_id, source, source_id, title, body, url, ticker, published_at, ingested_at, metadata)
            VALUES (?,?,?,?,?,?,?,?,?,?)""", new_docs)
    print(f"quartr transcripts: {len(new_docs)} new")


if __name__ == "__main__":
    sys.exit(main() or 0)
