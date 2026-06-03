#!/usr/bin/env python3
"""Embed every document in knowledge.duckdb with BAAI/bge-small-en-v1.5.

Lightweight (ONNX, no torch). 384-dim vectors. Stored in `doc_embeddings`
with a DuckDB HNSW index for fast cosine queries.

Usage:
  python3 scripts/embed.py                # embed any unseen docs
  python3 scripts/embed.py --rebuild      # drop + rebuild index
  python3 scripts/embed.py --status       # show coverage + index stats
"""
from __future__ import annotations
import argparse, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
KB = ROOT / "data" / "knowledge.duckdb"
MODEL_ID = "BAAI/bge-small-en-v1.5"
DIM = 384
BATCH = 64
MAX_CHARS = 2000  # cap per doc — embedding model truncates anyway

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS doc_embeddings (
    doc_id     VARCHAR PRIMARY KEY,
    model      VARCHAR NOT NULL,
    embedded_at TIMESTAMP DEFAULT now(),
    vec        FLOAT[{DIM}]
);
"""


def get_embedder():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL_ID)


def embed_batch(model, texts: list[str]) -> list[list[float]]:
    return [list(map(float, v)) for v in model.embed(texts)]


def status(con):
    n_docs = con.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_emb = con.execute("SELECT COUNT(*) FROM doc_embeddings").fetchone()[0]
    print(f"documents: {n_docs}")
    print(f"embedded:  {n_emb}  ({n_emb/max(n_docs,1)*100:.1f}%)")
    by_src = con.execute(
        """SELECT d.source, COUNT(*) FILTER (WHERE e.doc_id IS NULL) AS pending,
                  COUNT(*) FILTER (WHERE e.doc_id IS NOT NULL) AS done
           FROM documents d LEFT JOIN doc_embeddings e USING (doc_id)
           GROUP BY d.source ORDER BY done+pending DESC"""
    ).fetchall()
    for s, p, d in by_src:
        print(f"  {s:30s}  done={d:6d}  pending={p:6d}")


def run(con, model, limit: int | None):
    pending = con.execute(
        """SELECT d.doc_id, COALESCE(d.title,'') || E'\\n' || COALESCE(d.body,'') AS text
           FROM documents d LEFT JOIN doc_embeddings e USING (doc_id)
           WHERE e.doc_id IS NULL"""
        + (f" LIMIT {int(limit)}" if limit else "")
    ).fetchall()
    if not pending:
        print("Nothing to embed.")
        return 0
    print(f"Embedding {len(pending)} documents with {MODEL_ID} (batch={BATCH})…")
    t0 = time.time()
    done = 0
    for i in range(0, len(pending), BATCH):
        batch = pending[i : i + BATCH]
        texts = [(t or "")[:MAX_CHARS] for _, t in batch]
        try:
            vecs = embed_batch(model, texts)
        except Exception as e:
            print(f"  batch {i} failed: {e}")
            continue
        rows = [(b[0], MODEL_ID, v) for b, v in zip(batch, vecs)]
        con.executemany(
            "INSERT OR REPLACE INTO doc_embeddings (doc_id, model, vec) VALUES (?, ?, ?)",
            rows,
        )
        done += len(rows)
        if done % (BATCH * 8) == 0 or done == len(pending):
            elapsed = time.time() - t0
            rate = done / max(elapsed, 0.1)
            eta = (len(pending) - done) / max(rate, 0.1)
            print(f"  {done}/{len(pending)}  ({rate:.0f}/s, eta {eta:.0f}s)")
    return done


def ensure_index(con):
    try:
        con.execute("INSTALL vss; LOAD vss;")
        con.execute("SET hnsw_enable_experimental_persistence = true;")
        con.execute(
            "CREATE INDEX IF NOT EXISTS doc_emb_hnsw ON doc_embeddings USING HNSW (vec) WITH (metric = 'cosine');"
        )
    except Exception as e:
        print(f"  index note: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    con = kb()
    con.execute(SCHEMA)
    if a.status:
        status(con); return
    if a.rebuild:
        con.execute("DROP INDEX IF EXISTS doc_emb_hnsw;")
        con.execute("DELETE FROM doc_embeddings;")
    model = get_embedder()
    n = run(con, model, a.limit)
    ensure_index(con)
    print(f"\nEmbedded {n} docs. Index ready.")
    status(con)


if __name__ == "__main__":
    main()
