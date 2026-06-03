#!/usr/bin/env python3
"""Self-wiring knowledge graph — extract ticker co-mentions from docs.

GBrain pattern: every doc write extracts entity refs and creates edges
with zero LLM calls. Here we scan title + body for universe tickers and
write (source, target, edge_type, count, last_seen) rows.

Output: knowledge.duckdb table `entity_edges`
"""
from __future__ import annotations
import re, sys
from pathlib import Path
import yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
TICKERS = sorted({t for syms in (UNIVERSE.get("universe") or {}).values() for t in (syms or [])})

# Stop set — common short codes that collide with English words.
COLLIDE_STOP = {"A", "I", "AI", "IT", "ON", "GO", "ALL", "AND", "FOR", "ARE"}
SAFE_TICKERS = [t for t in TICKERS if t not in COLLIDE_STOP and len(t) >= 2]
# pre-compile per-ticker regex with word boundaries; allow $TICK syntax too
PATTERNS = {t: re.compile(rf"(?:\$|[^A-Z0-9_]){re.escape(t)}(?:[^A-Z0-9_]|$)") for t in SAFE_TICKERS}


def init_schema(con):
    con.execute("""
        CREATE TABLE IF NOT EXISTS entity_edges (
            source_ticker VARCHAR NOT NULL,
            target_ticker VARCHAR NOT NULL,
            edge_type     VARCHAR NOT NULL DEFAULT 'co_mention',
            count         INTEGER NOT NULL DEFAULT 0,
            first_seen    TIMESTAMP,
            last_seen     TIMESTAMP,
            PRIMARY KEY (source_ticker, target_ticker, edge_type)
        );
    """)


def extract(con, since_days: int | None = None) -> int:
    """Walk docs and build co-mention edges."""
    where = "1=1"
    params = []
    if since_days:
        where = "ingested_at >= now() - INTERVAL '%d days'" % since_days
    rows = con.execute(
        f"""SELECT doc_id, ticker, title, COALESCE(body, '') AS body, ingested_at
           FROM documents WHERE {where}""",
        params,
    ).fetchall()

    pair_counts: dict[tuple[str, str], dict] = {}
    for doc_id, src_t, title, body, ingested in rows:
        text = ((title or "") + " " + body[:2000])  # cap body scan
        hits = [t for t, pat in PATTERNS.items() if pat.search(" " + text + " ")]
        if not hits:
            continue
        # Pair every hit with every other hit (undirected) AND with the
        # doc's primary ticker if present and not in hits.
        all_tickers = set(hits)
        if src_t:
            all_tickers.add(src_t)
        tickers = sorted(all_tickers)
        for i, a in enumerate(tickers):
            for b in tickers[i+1:]:
                k = (a, b)
                rec = pair_counts.setdefault(k, {"count": 0, "first": ingested, "last": ingested})
                rec["count"] += 1
                if ingested and (not rec["first"] or ingested < rec["first"]):
                    rec["first"] = ingested
                if ingested and (not rec["last"] or ingested > rec["last"]):
                    rec["last"] = ingested

    # Upsert into entity_edges (we replace counts for full recompute, simple)
    con.execute("DELETE FROM entity_edges WHERE edge_type = 'co_mention'")
    rows_to_insert = []
    for (a, b), rec in pair_counts.items():
        rows_to_insert.append((a, b, "co_mention", rec["count"], rec["first"], rec["last"]))
        rows_to_insert.append((b, a, "co_mention", rec["count"], rec["first"], rec["last"]))
    if rows_to_insert:
        con.executemany(
            "INSERT INTO entity_edges VALUES (?, ?, ?, ?, ?, ?)",
            rows_to_insert,
        )
    return len(pair_counts)


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--since", type=int, default=None, help="restrict to last N days")
    p.add_argument("--show", type=str, default=None, help="show top edges for ticker")
    p.add_argument("--top", type=int, default=10)
    a = p.parse_args()

    con = kb()
    init_schema(con)
    n = extract(con, a.since)
    print(f"Extracted {n} unique ticker pairs (co-mention edges)")

    if a.show:
        rows = con.execute(
            """SELECT target_ticker, count, last_seen FROM entity_edges
               WHERE source_ticker = ? AND edge_type = 'co_mention'
               ORDER BY count DESC LIMIT ?""",
            [a.show, a.top],
        ).fetchall()
        print(f"\nTop co-mentions for {a.show}:")
        for tgt, c, last in rows:
            print(f"  {tgt:>6}  count={c:>4}  last={str(last)[:10]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
