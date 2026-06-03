#!/usr/bin/env python3
"""Unified, manipulation-aware social-sentiment engine (the "superpower" layer).

This supersedes the single-source scripts/signals/x_sentiment.py. It reads ALL
social/news documents already ingested into knowledge.duckdb (`documents`
table) — X, StockTwits, Reddit, news, and any licensed third-party feed — and
turns them into ONE disciplined, contrarian-aware signal per ticker.

Design principles (why this is built the way it is):

  1. Social sentiment is the most easily MANIPULATED input in the whole system.
     Low-float AI names get coordinated pumps daily. So the engine's first job
     is to *defend against being fooled*, not to amplify the loudest voices.
       - Each post is re-scored with the finance lexicon (negation, intensity,
         hype/spam). Pump language is scored as manipulation risk, not bullishness.
       - High manipulation risk VETOES a ticker's sentiment contribution.
       - Engagement is down-weighted when manipulation risk is high (pumps buy
         fake engagement).
       - "Breadth" (how many *distinct credible authors* agree) matters more than
         raw volume, so one megaphone account cannot move conviction.

  2. Extreme bullish sentiment is often a TOP, not a buy. Euphoria (very high
     sentiment + volume spike + everyone agreeing) is flagged and CAPPED for new
     entries — mirroring the doctrine engine's RSI-euphoria = "crowded" lens.

  3. The genuinely useful signal is sentiment-vs-PRICE DIVERGENCE:
       - price rising while sentiment deteriorates  -> distribution (dampen)
       - price falling while sentiment improves      -> possible capitulation
     The engine computes this when price data is available.

  4. Sentiment is a WEAK CONFIRMATION / VETO overlay, never a primary driver.
     Its conviction contribution is small and bounded — consistent with the
     repo's own doctrine (tier-4 sentiment weight = 0.10, "treat carefully").

  5. Thin or STALE data contributes NOTHING and is disclosed, never guessed.

Output: one row per ticker in `signals` with signal_name='social_sentiment'
(value = contrarian-adjusted composite in [-1, +1]); metadata carries every
component so the recommender can explain and gate on it. For backward
compatibility it also writes `x_sentiment` rows for the X-only subset so existing
downstream code keeps working unchanged.

Informational only. Not financial advice.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = next(
    (p for p in Path(__file__).resolve().parents
     if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()),
    Path(__file__).resolve().parents[2],
)
sys.path.insert(0, str(ROOT / "scripts"))

from signals.sentiment_lexicon import analyze_text  # noqa: E402

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

KB_DB = ROOT / "data" / "knowledge.duckdb"
PRICES_DB = ROOT / "data" / "prices.duckdb"
REPORTS = ROOT / "reports"
CONFIG = ROOT / "config" / "sentiment_sources.yaml"
FINTWIT = ROOT / "config" / "fintwit_handles.yaml"

# ----------------------------------------------------------------- defaults -- #
# Everything here is overridable in config/sentiment_sources.yaml. The defaults
# encode the safety posture so the engine is sane even with no config file.
DEFAULTS: dict[str, Any] = {
    "recent_days": 7,
    "baseline_days": 60,
    "staleness_days": 4,          # newest post older than this -> stale, no contribution
    "min_authors": 3,             # fewer distinct authors -> low confidence
    "min_posts": 5,
    "decay_half_life_days": 3.0,  # recency weighting within the recent window
    # source base credibility (0-1). News/known finance > anonymous social.
    "source_weights": {
        "news": 1.0, "rss": 1.0, "finviz": 0.9, "reuters": 1.0, "yahoo": 0.8,
        "stocktwits": 0.55, "x": 0.6, "reddit": 0.45, "truthsocial": 0.5,
        "facebook": 0.4, "provider": 0.6, "default": 0.5,
    },
    # author-tier multipliers applied on top of source weight
    "author_tiers": {"trusted": 1.6, "known": 1.2, "unknown": 1.0, "suspect": 0.4},
    # manipulation gate
    "manip_veto_threshold": 0.45,   # >= this -> sentiment contribution vetoed
    "manip_dampen_threshold": 0.25,  # >= this -> contribution scaled down
    # euphoria detection (crowded-long / exhaustion)
    "euphoria_sentiment": 0.55,
    "euphoria_volume_z": 1.5,
    "euphoria_max_dispersion": 0.35,
    # divergence
    "divergence_lookback": 5,
    # final conviction contribution bound (points added to the 0-100 score)
    "max_conviction_points": 8,
}


def _load_yaml(path: Path) -> dict:
    if yaml is None or not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text()) or {}
    except Exception:
        return {}


def _cfg() -> dict:
    cfg = dict(DEFAULTS)
    user = _load_yaml(CONFIG)
    for k, v in user.items():
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            merged = dict(cfg[k]); merged.update(v); cfg[k] = merged
        else:
            cfg[k] = v
    return cfg


def _trusted_handles() -> set[str]:
    """Handles the operator has vetted (from fintwit_handles.yaml)."""
    fh = _load_yaml(FINTWIT)
    handles: set[str] = set()
    for k, v in fh.items():
        if isinstance(v, list):
            for h in v:
                if isinstance(h, str) and "—" not in h and "exclude" not in h.lower():
                    handles.add(h.lstrip("@").strip().lower())
    return handles


def _source_kind(source: str) -> str:
    s = (source or "").lower()
    for key in ("stocktwits", "truthsocial", "facebook", "reddit", "finviz",
                "reuters", "yahoo", "provider"):
        if key in s:
            return key
    if s.startswith("x:") or s == "x":
        return "x"
    if s.startswith("rss") or "news" in s:
        return "news"
    return "default"


# ------------------------------------------------------------- data loading -- #
def fetch_docs(con, baseline_days: int) -> pd.DataFrame:
    cutoff = date.today() - timedelta(days=baseline_days)
    cols = "doc_id, source, source_id, ticker, title, body, url, published_at, ingested_at, metadata"
    try:
        rows = con.execute(
            f"SELECT {cols} FROM documents WHERE COALESCE(published_at, ingested_at) >= ?",
            [cutoff],
        ).fetchdf()
    except Exception:
        return pd.DataFrame()
    if rows.empty:
        return rows

    def _meta(s):
        try:
            return json.loads(s) if s else {}
        except Exception:
            return {}

    meta = rows["metadata"].apply(_meta)
    rows["m_ticker"] = meta.apply(lambda m: (m.get("ticker") or ""))
    rows["ticker"] = rows.apply(
        lambda r: (str(r["ticker"]) if pd.notna(r["ticker"]) and r["ticker"] else r["m_ticker"]),
        axis=1,
    ).str.upper().str.strip()
    rows["handle"] = meta.apply(lambda m: (m.get("handle") or m.get("author") or "")).str.lower()
    rows["likes"] = meta.apply(lambda m: float(m.get("likes", m.get("score", 0)) or 0))
    rows["reposts"] = meta.apply(lambda m: float(m.get("retweets", m.get("reblogs", m.get("comments", 0))) or 0))
    rows["posted_at"] = pd.to_datetime(
        rows["published_at"].fillna(rows["ingested_at"]), errors="coerce", utc=True
    )
    rows["text"] = rows["body"].fillna("").where(rows["body"].astype(bool), rows["title"].fillna(""))
    rows = rows.dropna(subset=["ticker", "posted_at"])
    rows = rows[rows["ticker"] != ""]
    return rows


def _recent_returns(tickers: list[str], lookback: int) -> dict[str, float]:
    """N-day pct return per ticker from prices.duckdb (best-effort)."""
    if not tickers or not PRICES_DB.exists():
        return {}
    try:
        import duckdb
        c = duckdb.connect(str(PRICES_DB), read_only=True)
        out: dict[str, float] = {}
        for t in tickers:
            try:
                df = c.execute(
                    "SELECT close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT ?",
                    [t, lookback + 1],
                ).fetchdf()
                if len(df) >= 2:
                    newest, oldest = float(df["close"].iloc[0]), float(df["close"].iloc[-1])
                    if oldest > 0:
                        out[t] = (newest - oldest) / oldest
            except Exception:
                continue
        c.close()
        return out
    except Exception:
        return {}


# ------------------------------------------------------------------- scoring - #
def score(rows: pd.DataFrame, cfg: dict, trusted: set[str], today: date) -> pd.DataFrame:
    empty_cols = ["ticker", "weighted_sentiment", "breadth", "volume_z", "dispersion",
                  "manipulation_risk", "euphoria_flag", "divergence", "n_posts",
                  "n_authors", "stale", "confidence", "composite", "conviction_points",
                  "x_composite", "x_sentiment_avg", "x_volume_z", "read"]
    if rows.empty:
        return pd.DataFrame(columns=empty_cols)

    now = pd.Timestamp(today, tz="UTC")
    rows = rows.copy()
    rows["age_days"] = (now - rows["posted_at"]).dt.total_seconds() / 86400.0
    rows["kind"] = rows["source"].apply(_source_kind)

    # per-post lexicon features
    feats = rows["text"].apply(analyze_text)
    rows["sentiment"] = feats.apply(lambda f: f["sentiment"])
    rows["hype"] = feats.apply(lambda f: f["hype"])
    rows["spam"] = feats.apply(lambda f: f["spam"])
    rows["n_terms"] = feats.apply(lambda f: f["n_terms"])

    sw = cfg["source_weights"]
    at = cfg["author_tiers"]
    hl = max(0.5, float(cfg["decay_half_life_days"]))

    def author_tier(h: str) -> str:
        if not h:
            return "unknown"
        if h in trusted:
            return "trusted"
        return "unknown"

    rows["src_w"] = rows["kind"].apply(lambda k: sw.get(k, sw.get("default", 0.5)))
    rows["auth_w"] = rows["handle"].apply(lambda h: at.get(author_tier(h), 1.0))
    rows["decay"] = np.power(0.5, rows["age_days"] / hl)
    # engagement weight, but DISCOUNTED by post-level manipulation markers
    rows["eng"] = np.log1p(rows["likes"] + 2 * rows["reposts"])
    rows["eng_w"] = 1.0 + 0.15 * rows["eng"] * (1.0 - rows[["hype", "spam"]].max(axis=1))
    rows["w"] = rows["src_w"] * rows["auth_w"] * rows["eng_w"] * rows["decay"]

    recent = rows[rows["age_days"] <= cfg["recent_days"]]
    base = rows[(rows["age_days"] > cfg["recent_days"]) & (rows["age_days"] <= cfg["baseline_days"])]

    results = []
    for tkr, g in recent.groupby("ticker"):
        wsum = g["w"].sum()
        if wsum <= 0:
            continue
        weighted_sent = float((g["w"] * g["sentiment"]).sum() / wsum)

        # breadth: distinct authors net-positive vs net-negative (anonymous posts
        # are pooled as a single low-weight voice to stop botnets inflating breadth)
        named = g[g["handle"] != ""]
        author_means = named.groupby("handle")["sentiment"].mean()
        n_authors = int(author_means.shape[0]) + (1 if (g["handle"] == "").any() else 0)
        if author_means.shape[0] > 0:
            pos = int((author_means > 0.1).sum()); neg = int((author_means < -0.1).sum())
            breadth = (pos - neg) / max(1, pos + neg)
        else:
            breadth = float(np.sign(weighted_sent))

        dispersion = float(g["sentiment"].std(ddof=0)) if len(g) > 1 else 0.0

        # volume spike vs trailing baseline daily rate
        n_recent = len(g)
        n_base = len(base[base["ticker"] == tkr])
        rate_recent = n_recent / max(1, cfg["recent_days"])
        rate_base = n_base / max(1, (cfg["baseline_days"] - cfg["recent_days"]))
        volume_z = (rate_recent - rate_base) / (rate_base + 0.5) if rate_base > 0 else float(rate_recent)

        # manipulation risk: post-level hype/spam (weighted) + author concentration
        # + near-duplicate density (botnets repost identical text).
        manip_post = float((g["w"] * g[["hype", "spam"]].max(axis=1)).sum() / wsum)
        top_author_share = float(named["w"].groupby(named["handle"]).sum().max() / wsum) if not named.empty else 0.0
        concentration_pen = max(0.0, top_author_share - 0.5)  # one author > 50% of weight
        dup_ratio = 1.0 - (g["text"].str.slice(0, 80).nunique() / max(1, len(g)))
        manipulation_risk = float(min(1.0, manip_post + 0.4 * concentration_pen + 0.3 * dup_ratio))

        # euphoria / crowded-long
        euphoria_flag = bool(
            weighted_sent >= cfg["euphoria_sentiment"]
            and volume_z >= cfg["euphoria_volume_z"]
            and dispersion <= cfg["euphoria_max_dispersion"]
        )

        # confidence from sample adequacy + (low) dispersion + freshness
        newest_age = float(g["age_days"].min())
        stale = newest_age > cfg["staleness_days"]
        sample_ok = min(1.0, n_authors / cfg["min_authors"]) * min(1.0, n_recent / cfg["min_posts"])
        confidence = float(max(0.0, min(1.0, sample_ok * (1.0 - 0.5 * dispersion))))

        results.append({
            "ticker": tkr, "weighted_sentiment": round(weighted_sent, 4),
            "breadth": round(breadth, 3), "volume_z": round(volume_z, 3),
            "dispersion": round(dispersion, 3),
            "manipulation_risk": round(manipulation_risk, 3),
            "euphoria_flag": euphoria_flag, "n_posts": int(n_recent),
            "n_authors": int(n_authors), "stale": bool(stale),
            "confidence": round(confidence, 3),
            # X-only subset for backward-compatible x_sentiment rows
            "_x_sent": float(g.loc[g["kind"] == "x", "sentiment"].mean()) if (g["kind"] == "x").any() else None,
            "_x_n": int((g["kind"] == "x").sum()),
        })

    df = pd.DataFrame(results)
    if df.empty:
        return pd.DataFrame(columns=empty_cols)

    # ---- divergence vs price -------------------------------------------- #
    rets = _recent_returns(df["ticker"].tolist(), cfg["divergence_lookback"])
    def diverge(row):
        r = rets.get(row["ticker"])
        if r is None:
            return 0.0
        s = row["weighted_sentiment"]
        # price up + weak/negative sentiment -> distribution (negative divergence)
        if r > 0.02 and s < 0.1:
            return -min(1.0, abs(r) * 5)
        # price down + positive sentiment -> possible capitulation/turn
        if r < -0.02 and s > 0.1:
            return +min(1.0, abs(r) * 5)
        return 0.0
    df["divergence"] = df.apply(diverge, axis=1)

    # ---- contrarian-aware composite ------------------------------------- #
    def composite(row):
        if row["stale"]:
            return 0.0, "stale (newest post too old) — no contribution"
        # base read = sentiment scaled by breadth (need agreement, not a megaphone)
        base_val = row["weighted_sentiment"] * (0.5 + 0.5 * abs(row["breadth"])) * np.sign(row["breadth"] or 1)
        base_val = float(np.clip(base_val, -1, 1))

        notes = []
        # manipulation gate
        if row["manipulation_risk"] >= cfg["manip_veto_threshold"]:
            return 0.0, f"manipulation suspected (risk {row['manipulation_risk']:.2f}) — sentiment VETOED"
        if row["manipulation_risk"] >= cfg["manip_dampen_threshold"]:
            base_val *= 0.5
            notes.append(f"manip-dampened ({row['manipulation_risk']:.2f})")

        # euphoria cap: don't chase a crowded top on a NEW entry
        if row["euphoria_flag"]:
            base_val = min(base_val, 0.1) - 0.15
            notes.append("euphoric/crowded — capped (chase risk)")

        # divergence adjustment
        if row["divergence"] != 0.0:
            base_val += 0.4 * row["divergence"]
            notes.append("price-distribution" if row["divergence"] < 0 else "price-capitulation")

        # confidence scaling
        base_val *= row["confidence"]
        base_val = float(np.clip(base_val, -1, 1))

        # human read
        if abs(base_val) < 0.08:
            tag = "neutral / not actionable"
        elif base_val > 0:
            tag = "supportive"
        else:
            tag = "cautionary"
        read = (f"social {tag} (sent {row['weighted_sentiment']:+.2f}, breadth {row['breadth']:+.2f}, "
                f"vol_z {row['volume_z']:+.2f}, authors {row['n_authors']}, conf {row['confidence']:.2f}"
                + (("; " + ", ".join(notes)) if notes else "") + ")")
        return base_val, read

    comp = df.apply(composite, axis=1)
    df["composite"] = [c[0] for c in comp]
    df["read"] = [c[1] for c in comp]
    df["conviction_points"] = (df["composite"] * cfg["max_conviction_points"]).round().astype(int)

    # back-compat x_sentiment fields
    df["x_composite"] = df["composite"]
    df["x_sentiment_avg"] = df["_x_sent"]
    df["x_volume_z"] = df["volume_z"]
    return df.sort_values("composite", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------- persistence - #
def write_signals(con, df: pd.DataFrame, asof: date) -> int:
    if df.empty:
        return 0
    keep = ["weighted_sentiment", "breadth", "volume_z", "dispersion",
            "manipulation_risk", "euphoria_flag", "divergence", "n_posts",
            "n_authors", "stale", "confidence", "composite", "conviction_points", "read"]
    rows_social, rows_x = [], []
    for i, r in df.iterrows():
        meta = {k: (bool(r[k]) if isinstance(r[k], (bool, np.bool_)) else
                    (r[k] if isinstance(r[k], str) else float(r[k]))) for k in keep}
        rows_social.append((asof, r["ticker"], "social_sentiment",
                            float(r["composite"]), int(i) + 1, json.dumps(meta)))
        # backward-compatible x_sentiment row (only where X posts existed)
        if r.get("_x_n", 0) and r.get("_x_n") > 0:
            xmeta = {"composite": float(r["composite"]),
                     "sentiment_avg": float(r["x_sentiment_avg"] or 0.0),
                     "volume_z": float(r["x_volume_z"]),
                     "engagement_z": 0.0}
            rows_x.append((asof, r["ticker"], "x_sentiment",
                           float(r["composite"]), int(i) + 1, json.dumps(xmeta)))

    con.execute("DELETE FROM signals WHERE signal_date = ? AND signal_name = 'social_sentiment'", [asof])
    con.executemany(
        """INSERT OR REPLACE INTO signals (signal_date, ticker, signal_name, value, rank, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""", rows_social)
    if rows_x:
        con.execute("DELETE FROM signals WHERE signal_date = ? AND signal_name = 'x_sentiment'", [asof])
        con.executemany(
            """INSERT OR REPLACE INTO signals (signal_date, ticker, signal_name, value, rank, metadata)
               VALUES (?, ?, ?, ?, ?, ?)""", rows_x)
    return len(rows_social)


def _write_report(df: pd.DataFrame):
    REPORTS.mkdir(exist_ok=True)
    payload = {
        "as_of": date.today().isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "n_tickers": int(len(df)),
        "tickers": (df.drop(columns=[c for c in ("_x_sent", "_x_n") if c in df.columns])
                    .to_dict(orient="records") if not df.empty else []),
        "note": "Contrarian-aware, manipulation-gated social sentiment. Weak confirmation overlay only. Not financial advice.",
    }
    (REPORTS / "social-sentiment-latest.json").write_text(json.dumps(payload, indent=2, default=str))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Unified manipulation-aware social sentiment.")
    ap.add_argument("--show", type=int, default=15)
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args(argv)

    import duckdb
    cfg = _cfg()
    trusted = _trusted_handles()
    con = duckdb.connect(str(KB_DB))
    rows = fetch_docs(con, cfg["baseline_days"])
    df = score(rows, cfg, trusted, date.today())

    n = 0 if a.no_write else write_signals(con, df, date.today())
    con.close()
    _write_report(df)

    if df.empty:
        print("social_sentiment: no social/news documents in the window yet.")
        print("Feed it via: scripts.ingest.{xurl_sentiment,stocktwits,reddit,news} then re-run.")
        return
    show_cols = ["ticker", "composite", "weighted_sentiment", "breadth", "volume_z",
                 "manipulation_risk", "euphoria_flag", "divergence", "n_authors", "confidence"]
    print(f"\nSocial sentiment — top {a.show} (contrarian-adjusted composite):")
    print(df[show_cols].head(a.show).to_string(index=False))
    if not a.no_write:
        print(f"\n{n} rows written (signal_name='social_sentiment'; x_sentiment mirror for X subset).")


if __name__ == "__main__":
    main()
