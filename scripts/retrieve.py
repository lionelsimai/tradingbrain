#!/usr/bin/env python3
"""Hybrid retrieval: BM25 + vector + RRF + tier/recency/graph boosts."""
from __future__ import annotations
import argparse, math, re, sys
from datetime import datetime, timezone
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
TICKERS = set()
for syms in (UNIVERSE.get("universe") or {}).values():
    for t in syms or []:
        TICKERS.add(t)

# Source tier boosts. Pulled from sources.yaml weights, normalised.
TIER_BOOST = {
    "edgar_filing": 1.40,
    "edgar_form4": 1.35,
    "fundamentals": 1.25,
    "fred": 1.20,
    "macro": 1.20,
    "rss:semianalysis_rss": 1.20,
    "rss:the_transcript_rss": 1.18,
    "web:datacenter_dynamics": 1.10,
    "web:datacenter_knowledge": 1.10,
    "yahoo_news": 1.05,
    "web:cnbc_markets": 1.05,
    "web:cnbc_tech": 1.05,
    "web:marketwatch_top": 1.05,
    "web:prnewswire": 1.00,
    "web:investing_com_stocks": 0.98,
    "hn": 0.92,
    "rss:arxiv_cs_ai": 0.85,
    "rss:arxiv_cs_lg": 0.85,
}

RRF_K = 60
RECENCY_HALFLIFE_DAYS = 30.0


def tier_boost(source: str) -> float:
    if source in TIER_BOOST:
        return TIER_BOOST[source]
    for prefix, b in TIER_BOOST.items():
        if source.startswith(prefix):
            return b
    if source.startswith("x:"):
        return 0.95
    return 1.0


def recency_factor(ingested_at) -> float:
    if ingested_at is None:
        return 0.6
    try:
        ts = ingested_at if isinstance(ingested_at, datetime) else datetime.fromisoformat(str(ingested_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        days = (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0
        return math.exp(-days / RECENCY_HALFLIFE_DAYS)
    except Exception:
        return 0.6


def extract_query_tickers(q: str) -> set[str]:
    out = set()
    for w in re.findall(r"\b[A-Z]{1,5}\b", q):
        if w in TICKERS:
            out.add(w)
    return out


def bm25_lane(con, query: str, k: int, ticker: str | None) -> list[tuple[str, float]]:
    safe = query.replace("'", " ")
    where = ["bm25 IS NOT NULL"]
    if ticker:
        where.append(f"ticker = '{ticker}'")
    sql = f"""
        SELECT doc_id, fts_main_documents.match_bm25(doc_id, '{safe}') AS bm25
        FROM documents
        QUALIFY {' AND '.join(where)}
        ORDER BY bm25 DESC NULLS LAST
        LIMIT {k}
    """
    try:
        return [(r[0], float(r[1] or 0)) for r in con.execute(sql).fetchall()]
    except Exception:
        # Older DuckDB QUALIFY edge case — fallback
        inner = f"""
            SELECT doc_id, fts_main_documents.match_bm25(doc_id, '{safe}') AS bm25, ticker
            FROM documents
        """
        wrap = f"SELECT doc_id, bm25 FROM ({inner}) WHERE {' AND '.join(where)} ORDER BY bm25 DESC NULLS LAST LIMIT {k}"
        return [(r[0], float(r[1] or 0)) for r in con.execute(wrap).fetchall()]


def vector_lane(con, query: str, k: int, ticker: str | None) -> list[tuple[str, float]]:
    from fastembed import TextEmbedding
    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    qv = list(model.embed([query]))[0].tolist()
    tfilter = f"AND d.ticker = '{ticker}'" if ticker else ""
    sql = f"""
        SELECT e.doc_id, array_cosine_similarity(e.vec, ?::FLOAT[384]) AS sim
        FROM doc_embeddings e JOIN documents d USING(doc_id)
        WHERE TRUE {tfilter}
        ORDER BY sim DESC
        LIMIT {k}
    """
    return [(r[0], float(r[1])) for r in con.execute(sql, [qv]).fetchall()]


def graph_boost_map(con, query_tickers: set[str]) -> dict[str, float]:
    """Docs that mention tickers co-mentioned with query tickers get a boost."""
    if not query_tickers:
        return {}
    placeholders = ",".join(f"'{t}'" for t in query_tickers)
    rows = con.execute(f"""
        SELECT target_ticker, SUM(count) FROM entity_edges
        WHERE source_ticker IN ({placeholders})
        GROUP BY target_ticker
    """).fetchall()
    return {t: 1.0 + min(0.30, 0.05 * math.log1p(c)) for t, c in rows if t}


def hybrid(query: str, k: int = 10, ticker: str | None = None, pool: int = 40, explain: bool = False):
    con = kb()
    bm = bm25_lane(con, query, pool, ticker)
    vc = vector_lane(con, query, pool, ticker)

    # RRF
    rrf = {}
    for rank, (doc, _) in enumerate(bm):
        rrf[doc] = rrf.get(doc, 0) + 1.0 / (RRF_K + rank + 1)
    for rank, (doc, _) in enumerate(vc):
        rrf[doc] = rrf.get(doc, 0) + 1.0 / (RRF_K + rank + 1)

    qtix = extract_query_tickers(query)
    gboost = graph_boost_map(con, qtix)

    docs = list(rrf.keys())
    if not docs:
        return []
    placeholders = ",".join(["?"] * len(docs))
    meta_rows = con.execute(f"""
        SELECT doc_id, source, title, ticker, url, ingested_at
        FROM documents WHERE doc_id IN ({placeholders})
    """, docs).fetchall()
    meta = {r[0]: r for r in meta_rows}

    scored = []
    for doc in docs:
        m = meta.get(doc)
        if not m:
            continue
        _, src, title, tick, url, ing = m
        s_rrf = rrf[doc]
        s_tier = tier_boost(src or "")
        s_rec = recency_factor(ing)
        s_graph = gboost.get(tick or "", 1.0)
        final = s_rrf * s_tier * s_rec * s_graph
        scored.append({
            "doc_id": doc, "source": src, "title": title, "ticker": tick,
            "url": url, "ingested_at": str(ing)[:19] if ing else None,
            "rrf": s_rrf, "tier": s_tier, "recency": s_rec, "graph": s_graph,
            "score": final,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--pool", type=int, default=40)
    ap.add_argument("--explain", action="store_true")
    a = ap.parse_args()
    results = hybrid(a.query, a.k, a.ticker, a.pool, a.explain)
    for i, r in enumerate(results, 1):
        line = f"{i:>2}. [{r['score']:.4f}] {r['source']:<24} {(r['ticker'] or '-'):>6}  {r['title'][:80]}"
        print(line)
        if a.explain:
            print(f"     rrf={r['rrf']:.4f} tier={r['tier']:.2f} rec={r['recency']:.3f} graph={r['graph']:.2f}")
        if r["url"]:
            print(f"     {r['url']}")


if __name__ == "__main__":
    main()
