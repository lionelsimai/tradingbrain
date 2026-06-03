#!/usr/bin/env python3
"""Ask Tape — semantic-retrieval-grounded Q&A over the brain.

Pulls top-k docs via scripts/retrieve.py, then calls /zo/ask with the
Tape persona so the synthesis stays in voice. Prints Tape's answer +
the citations that fed it.

Usage:
  python3 scripts/ask.py "what's the bull case for CEG?"
  python3 scripts/ask.py "how does AVGO compete with NVDA on margin?" --k 8
  python3 scripts/ask.py "summarize the last 10 NVDA 8-Ks" --ticker NVDA --since 180
"""
from __future__ import annotations
import argparse, os, textwrap
from datetime import date, timedelta
from pathlib import Path
import duckdb, requests

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SYSTEM_PROMPT_PATH = ROOT / "prompts" / "super-agent-sys.md"
SYSTEM_PROMPT = SYSTEM_PROMPT_PATH.read_text() if SYSTEM_PROMPT_PATH.exists() else ""
KB = ROOT / "data" / "knowledge.duckdb"
TAPE_PERSONA_ID = "87d92472-2c35-4076-8e35-53973775d8a7"
ZO_API = "https://api.zo.computer/zo/ask"
MODEL = "anthropic:claude-opus-4-7"


def embed_query(q: str) -> list[float]:
    from fastembed import TextEmbedding
    m = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
    return list(map(float, next(m.embed([q]))))


def retrieve(question: str, k: int, ticker: str | None, since_days: int) -> list[dict]:
    qvec = embed_query(question)
    con = duckdb.connect(str(KB), read_only=True)
    con.execute("INSTALL vss; LOAD vss;")
    cutoff = date.today() - timedelta(days=since_days)
    where = ["e.vec IS NOT NULL", "d.ingested_at >= ?"]
    params: list = [cutoff]
    if ticker:
        where.append("(d.ticker = ? OR d.body ILIKE ?)")
        params.extend([ticker.upper(), f"%{ticker.upper()}%"])
    sql = f"""
        SELECT d.doc_id, d.source, d.title, d.url, d.body, d.ingested_at, d.ticker,
               array_cosine_similarity(e.vec, ?::FLOAT[384]) AS cos
        FROM documents d JOIN doc_embeddings e USING (doc_id)
        WHERE {' AND '.join(where)}
        ORDER BY cos DESC LIMIT {k * 4}
    """
    rows = con.execute(sql, [qvec, *params]).fetchall()
    out = []
    for did, src, title, url, body, ing, tk, cos in rows[: k * 4]:
        out.append({
            "doc_id": did, "source": src, "title": title or "",
            "url": url or "", "body_excerpt": (body or "")[:600],
            "ingested_at": str(ing)[:10], "ticker": tk, "cos": round(float(cos or 0), 4),
        })
    # de-dup by title, keep best
    seen = set(); uniq = []
    for r in out:
        key = (r["source"], r["title"][:60])
        if key in seen: continue
        seen.add(key); uniq.append(r)
        if len(uniq) >= k: break
    return uniq


def build_prompt(question: str, evidence: list[dict]) -> str:
    parts = [
        f"Question: {question}",
        "",
        "Evidence retrieved from Lionel's TradingBrain knowledge base "
        "(EDGAR, FRED, Yahoo, arXiv, RSS, FinTwit):",
        "",
    ]
    for i, e in enumerate(evidence, 1):
        parts.append(
            f"[{i}] {e['source']} · {e['ticker'] or ''} · {e['ingested_at']} · cos={e['cos']}\n"
            f"    title: {e['title']}\n"
            f"    url:   {e['url']}\n"
            f"    excerpt: {e['body_excerpt'][:400].strip()}\n"
        )
    parts.append(textwrap.dedent("""\
        Answer as Tape. Be concise and opinionated. Cite evidence by its
        [#] index. If the evidence does not support a strong claim, say so
        and propose the next data pull. Default ~6-10 lines. End with
        'Bull / Bear / What would change my mind' only if the question
        is a thesis question.
    """))
    return "\n".join(parts)


def call_zo(prompt: str) -> str:
    tok = os.environ.get("ZO_CLIENT_IDENTITY_TOKEN", "")
    if not tok:
        return "(ZO_CLIENT_IDENTITY_TOKEN not set — printing evidence only.)"
    r = requests.post(
        ZO_API,
        headers={"authorization": tok, "content-type": "application/json"},
        json={"input": prompt, "model_name": MODEL, "persona_id": TAPE_PERSONA_ID},
        timeout=120,
    )
    r.raise_for_status()
    return r.json().get("output", "(empty)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="+")
    ap.add_argument("--k", type=int, default=6)
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--since", type=int, default=180)
    ap.add_argument("--evidence-only", action="store_true")
    a = ap.parse_args()
    q = " ".join(a.question)
    ev = retrieve(q, a.k, a.ticker, a.since)
    if not ev:
        print("(no evidence in the brain yet — try a broader window or run a backfill)")
        return
    if a.evidence_only:
        for i, e in enumerate(ev, 1):
            print(f"[{i}] {e['source']} {e['ticker'] or ''} {e['ingested_at']}  "
                  f"cos={e['cos']}\n    {e['title']}\n    {e['url']}\n")
        return
    prompt = build_prompt(q, ev)
    print(call_zo(prompt))
    print("\n— citations —")
    for i, e in enumerate(ev, 1):
        print(f"  [{i}] {e['source']} {e['ticker'] or ''} {e['ingested_at']}  {e['title'][:80]}")


if __name__ == "__main__":
    main()
