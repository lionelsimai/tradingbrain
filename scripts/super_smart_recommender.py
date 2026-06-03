#!/usr/bin/env python3
"""Self-auditing, research-only US stock recommender overlay for TradingBrain.

This is the "ask where I am lacking, then recommend anyway with evidence
ceilings" layer. It does not execute trades. It combines the current AI/US
stock pattern rank, strict TradingBrain picks, outlier/target/macro overlays,
and a capability audit that makes missing evidence explicit.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb
import yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "config" / "universe.yaml").exists()), Path.cwd())
REPORTS = ROOT / "reports"
DATA = ROOT / "data"
PRICES = DATA / "prices.duckdb"
KB = DATA / "knowledge.duckdb"
REPORTS.mkdir(exist_ok=True)

DISCLAIMER = (
    "Research-only decision support, not financial advice or an instruction to trade. "
    "TradingBrain remains paper/research mode until forward evidence, PIT data, and human review gates improve."
)


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _round(x: Any, n: int = 2):
    try:
        f = float(x)
        if not math.isfinite(f):
            return None
        return round(f, n)
    except Exception:
        return None


def _pct(n: float, d: float) -> float:
    return float(n) / float(d) if d else 0.0


def _severity(ok: bool, degraded: bool = False) -> str:
    if ok:
        return "ok"
    return "medium" if degraded else "high"


def summarize_capability_gaps(
    *,
    universe_count: int,
    price_ticker_count: int,
    has_point_in_time_universe: bool,
    delisted_included_pct: float,
    forward_paper_trades: int,
    analyst_target_records: int,
    fresh_fundamental_ticker_pct: float,
    fresh_news_ticker_pct: float,
    social_ticker_pct: float,
    pit_status: str | None = None,
    forward_paper_observations: int = 0,
    forward_paper_resolved: int = 0,
) -> list[dict[str, Any]]:
    """Return explicit missing layers that cap recommender intelligence."""
    gaps: list[dict[str, Any]] = []

    broad_enough = universe_count >= 500 and price_ticker_count >= 500
    gaps.append({
        "id": "universe_breadth",
        "status": "closed" if broad_enough else "limited",
        "severity": "ok" if broad_enough else ("critical" if universe_count < 150 else "high"),
        "evidence": f"configured_universe={universe_count}, priced_tickers={price_ticker_count}",
        "why_it_matters": "A true US stock recommender should scan a broad US equity universe, not only the current AI/watchlist universe.",
        "build_next": "Add a liquid-US-stock discovery universe from Polygon/Nasdaq listings, then price/rank at least 500-1500 tradable names.",
    })

    pit_ok = has_point_in_time_universe and delisted_included_pct >= 80
    pit_partial = (pit_status == "partial") or delisted_included_pct > 0
    gaps.append({
        "id": "point_in_time_survivorship",
        "status": "closed" if pit_ok else ("partial_reference" if pit_partial else "open"),
        "severity": "ok" if pit_ok else ("high" if pit_partial else "critical"),
        "evidence": f"point_in_time_universe={has_point_in_time_universe}, pit_status={pit_status or 'unknown'}, delisted_included_pct={delisted_included_pct}",
        "why_it_matters": "Backtests on all-alive universes overstate edge and miss dead-name losers.",
        "build_next": "Promote Polygon inactive/corporate-action reference into a survivorship-free PIT universe or import Sharadar/Norgate/Intrinio PIT data.",
    })

    effective_forward = max(int(forward_paper_trades or 0), int(forward_paper_resolved or 0))
    fwd_ok = effective_forward >= 200
    fwd_accumulating = int(forward_paper_observations or 0) > 0
    gaps.append({
        "id": "forward_paper_evidence",
        "status": "closed" if fwd_ok else ("accumulating_pending_outcomes" if fwd_accumulating else "open"),
        "severity": "ok" if fwd_ok else ("high" if fwd_accumulating else "critical"),
        "evidence": f"forward_paper_trades={forward_paper_trades}, observations={forward_paper_observations}, resolved={forward_paper_resolved}",
        "why_it_matters": "Replay/backtest edge must survive daily forward paper observations before confidence can be high.",
        "build_next": "Keep premarket/EOD paper loops running and require 200+ resolved forward observations across regimes.",
    })

    target_ok = analyst_target_records >= 200
    gaps.append({
        "id": "analyst_target_provenance",
        "status": "closed" if target_ok else "missing",
        "severity": "ok" if target_ok else "high",
        "evidence": f"analyst_target_records={analyst_target_records}",
        "why_it_matters": "External/banker targets can be stale, concentrated, or promotional unless broker/analyst/date/source provenance is tracked.",
        "build_next": "Ingest lawful analyst target records with ticker, broker, analyst, rating, target, date, source_url, and independence/dispersion checks.",
    })

    fresh_ok = fresh_fundamental_ticker_pct >= 0.8 and fresh_news_ticker_pct >= 0.8
    gaps.append({
        "id": "fresh_fundamental_catalyst_coverage",
        "status": "closed" if fresh_ok else "partial",
        "severity": "ok" if fresh_ok else "medium",
        "evidence": f"fresh_fundamental_ticker_pct={fresh_fundamental_ticker_pct:.1%}, fresh_news_ticker_pct={fresh_news_ticker_pct:.1%}",
        "why_it_matters": "A stock recommender needs fresh earnings, fundamentals, filings, and catalyst context, not just price momentum.",
        "build_next": "Run/expand fundamentals, EDGAR, news, earnings-calendar, and transcript ingestion; require freshness badges on each pick.",
    })

    social_ok = social_ticker_pct >= 0.7
    gaps.append({
        "id": "sentiment_manipulation_coverage",
        "status": "closed" if social_ok else "partial",
        "severity": "ok" if social_ok else "medium",
        "evidence": f"social_ticker_pct={social_ticker_pct:.1%}",
        "why_it_matters": "Crowded/euphoric/manipulated social flow can turn a good chart into a bad chase.",
        "build_next": "Continue lawful social sentiment ingestion and require manipulation/euphoria checks on each candidate.",
    })

    return gaps


def score_candidate_intelligence(candidate: dict[str, Any], overlays: dict[str, Any]) -> dict[str, Any]:
    """Blend candidate pattern strength with evidence quality and risk gates."""
    ticker = str(candidate.get("ticker", "")).upper()
    score = float(candidate.get("composite_score") or candidate.get("score") or 0.0)
    why: list[str] = []
    gaps: list[str] = []
    risks: list[str] = []

    if overlays.get("strict_pick"):
        score += 6
        why.append("Passed strict TradingBrain short-term gate / defined-risk recommender.")

    upside = candidate.get("target_upside_pct")
    if isinstance(upside, (int, float)):
        if upside >= 20:
            score += 4
            why.append(f"Technical scenario has high modeled upside ({upside:.1f}%).")
        elif upside >= 10:
            score += 2
            why.append(f"Technical scenario has moderate modeled upside ({upside:.1f}%).")

    rr = candidate.get("reward_risk")
    if isinstance(rr, (int, float)):
        if rr >= 2:
            score += 4
            why.append(f"Reward/risk clears strict threshold ({rr:.2f}R).")
        elif rr < 1.5:
            score -= 5
            risks.append(f"Reward/risk is thin ({rr:.2f}R).")

    if (candidate.get("return_1y_pct") or 0) > 100 and (candidate.get("return_6m_pct") or 0) > 40:
        why.append("Strong 1Y and 6M trend persistence / institutional momentum.")
    if (candidate.get("rel_1y_vs_qqq_pct") or 0) > 50:
        why.append("Material relative strength versus QQQ.")

    dd = abs(float(candidate.get("max_drawdown_3y_pct") or 0.0))
    if dd >= 70:
        score -= 8; risks.append(f"Very deep historical drawdown ({dd:.0f}%).")
    elif dd >= 55:
        score -= 3; risks.append(f"High-beta drawdown history ({dd:.0f}%).")

    outlier = overlays.get("outlier") or {}
    outlier_risk = str(outlier.get("risk_level", "low")).lower()
    if outlier.get("veto") or outlier_risk == "high":
        score -= 25
        risks.append("Outlier/abnormal trading risk requires human review before action.")
    elif outlier_risk in {"medium", "watch"}:
        score -= 8
        risks.append("Medium outlier/abnormality risk; wait for confirmation.")

    macro_risk = str(overlays.get("macro_risk", "low")).lower()
    if macro_risk == "high":
        score -= 10; risks.append("High macro/rates event risk near the decision window.")
    elif macro_risk == "medium":
        score -= 5; risks.append("Medium macro/rates event risk.")

    tq = overlays.get("target_quality") or {}
    tq_cautions = " ".join(tq.get("cautions") or [])
    if "No analyst-target provenance" in tq_cautions or tq.get("verdict") == "usable_but_discount_confidence":
        score -= 3
        gaps.append("Missing analyst-target provenance; external/banker targets are not trusted.")

    evidence = overlays.get("evidence") or {}
    if not evidence.get("fundamentals_available"):
        gaps.append("Fresh fundamental/value-quality evidence missing or stale.")
        score -= 2
    if int(evidence.get("recent_documents_14d") or 0) == 0:
        gaps.append("No fresh news/filing/catalyst document in the last 14 days.")
        score -= 2
    if not evidence.get("social_available"):
        gaps.append("Social/manipulation sentiment unavailable for this ticker.")
        score -= 1

    score = max(0.0, min(100.0, score))
    if outlier.get("veto") or outlier_risk == "high":
        label = "avoid_until_review"
        ceiling = "low"
    elif score >= 75:
        label = "top_research_candidate"
        ceiling = "moderate" if gaps else "high"
    elif score >= 60:
        label = "watch_to_accumulate"
        ceiling = "moderate" if len(gaps) <= 2 else "low"
    else:
        label = "conditional_watch_only"
        ceiling = "low"
    if tq.get("confidence_adjustment") == "reduce one notch" and ceiling == "high":
        ceiling = "moderate"

    return {
        "ticker": ticker,
        "sector": candidate.get("sector"),
        "recommender_score": round(score, 1),
        "action_label": label,
        "confidence_ceiling": ceiling,
        "last_close": candidate.get("last_close"),
        "setup": candidate.get("setup"),
        "modeled_upside_pct": _round(candidate.get("target_upside_pct"), 1),
        "reward_risk": _round(candidate.get("reward_risk"), 2),
        "return_3y_pct": _round(candidate.get("return_3y_pct"), 1),
        "return_1y_pct": _round(candidate.get("return_1y_pct"), 1),
        "return_6m_pct": _round(candidate.get("return_6m_pct"), 1),
        "max_drawdown_3y_pct": _round(candidate.get("max_drawdown_3y_pct"), 1),
        "why_it_scores": why or ["Positive composite pattern score, but evidence stack is incomplete."],
        "evidence_gaps": gaps,
        "red_team_risks": risks or ["No hard veto found, but still research-only and subject to regime reversal."],
        "source_candidate": candidate,
    }


def _universe_count() -> int:
    try:
        data = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text()) or {}
        return sum(len(v or []) for v in (data.get("universe") or {}).values())
    except Exception:
        return 0


def _price_ticker_count() -> int:
    try:
        con = duckdb.connect(str(PRICES), read_only=True)
        n = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
        con.close()
        return int(n or 0)
    except Exception:
        return 0


def _knowledge_coverage(tickers: list[str]) -> dict[str, Any]:
    out = {
        "fresh_fundamental_ticker_pct": 0.0,
        "fresh_news_ticker_pct": 0.0,
        "social_ticker_pct": 0.0,
        "forward_paper_trades": 0,
        "forward_paper_observations": 0,
        "forward_paper_resolved": 0,
        "analyst_target_records": 0,
        "per_ticker": {},
    }
    if not tickers:
        return out
    for t in tickers:
        out["per_ticker"][t] = {
            "fundamentals_available": False,
            "recent_documents_14d": 0,
            "social_available": False,
        }
    try:
        con = duckdb.connect(str(KB), read_only=True)
    except Exception:
        return out
    try:
        tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        placeholders = ",".join(["?"] * len(tickers))
        facts: set[str] = set()
        docs: dict[str, int] = {}
        social: set[str] = set()
        if "facts" in tables:
            facts = {r[0] for r in con.execute(
                f"SELECT DISTINCT ticker FROM facts WHERE ticker IN ({placeholders})",
                tickers,
            ).fetchall()}
        if "documents" in tables:
            cutoff = (datetime.now(timezone.utc) - timedelta(days=14)).replace(tzinfo=None)
            docs = {r[0]: int(r[1]) for r in con.execute(
                f"SELECT ticker, COUNT(*) FROM documents WHERE ticker IN ({placeholders}) AND COALESCE(published_at, ingested_at) >= ? GROUP BY ticker",
                tickers + [cutoff],
            ).fetchall()}
        if "signals" in tables:
            social = {r[0] for r in con.execute(
                f"SELECT DISTINCT ticker FROM signals WHERE signal_name IN ('social_sentiment','x_sentiment') AND ticker IN ({placeholders})",
                tickers,
            ).fetchall()}
        for t in tickers:
            out["per_ticker"][t] = {
                "fundamentals_available": t in facts,
                "recent_documents_14d": docs.get(t, 0),
                "social_available": t in social,
            }
        out["fresh_fundamental_ticker_pct"] = _pct(len(facts), len(tickers))
        out["fresh_news_ticker_pct"] = _pct(sum(1 for t in tickers if docs.get(t, 0) > 0), len(tickers))
        out["social_ticker_pct"] = _pct(len(social), len(tickers))
        if "signal_ledger" in tables:
            out["forward_paper_trades"] = int(con.execute("SELECT COUNT(*) FROM signal_ledger WHERE source='paper'").fetchone()[0] or 0)
        if "forward_paper_observations" in tables:
            out["forward_paper_observations"] = int(con.execute("SELECT COUNT(*) FROM forward_paper_observations").fetchone()[0] or 0)
            out["forward_paper_resolved"] = int(con.execute("SELECT COUNT(*) FROM forward_paper_observations WHERE realized_R IS NOT NULL OR status='resolved'").fetchone()[0] or 0)
        if "analyst_targets" in tables:
            out["analyst_target_records"] = int(con.execute("SELECT COUNT(*) FROM analyst_targets").fetchone()[0] or 0)
        else:
            # Backward compatibility: old target ingestion wrote JSONL only.
            try:
                path = ROOT / "data" / "raw" / "analyst_targets" / "targets.jsonl"
                out["analyst_target_records"] = len([ln for ln in path.read_text().splitlines() if ln.strip()]) if path.exists() else 0
            except Exception:
                out["analyst_target_records"] = 0
    except Exception:
        pass
    finally:
        con.close()
    return out


def _candidate_entry(candidate: dict[str, Any]) -> float | None:
    zone = candidate.get("entry_zone")
    if isinstance(zone, dict):
        low = _round(zone.get("low"), 4)
        high = _round(zone.get("high"), 4)
        if low is not None and high is not None:
            return (low + high) / 2.0
        return low if low is not None else high
    for key in ("entry", "last_close", "close", "price"):
        value = _round(candidate.get(key), 4)
        if value is not None:
            return value
    return None


def _candidate_target(candidate: dict[str, Any]) -> float | None:
    targets = candidate.get("targets")
    if isinstance(targets, list) and targets:
        first = targets[0]
        if isinstance(first, dict):
            value = _round(first.get("level") or first.get("target") or first.get("price"), 4)
            if value is not None:
                return value
        value = _round(first, 4)
        if value is not None:
            return value
    for key in ("target", "target_price", "take_profit", "t1"):
        value = _round(candidate.get(key), 4)
        if value is not None:
            return value
    return None


def _candidate_reward_risk(candidate: dict[str, Any]) -> float | None:
    explicit = _round(candidate.get("reward_risk") or candidate.get("reward_to_risk"), 3)
    if explicit is not None:
        return explicit
    entry = _candidate_entry(candidate)
    target = _candidate_target(candidate)
    stop = _round(candidate.get("stop_loss") or candidate.get("stop"), 4)
    if entry is None or target is None or stop is None or stop >= entry:
        return None
    return round((target - entry) / (entry - stop), 3)


def _candidate_upside(candidate: dict[str, Any]) -> float | None:
    explicit = _round(candidate.get("target_upside_pct") or candidate.get("modeled_upside_pct"), 2)
    if explicit is not None:
        return explicit
    entry = _candidate_entry(candidate)
    target = _candidate_target(candidate)
    if entry and target:
        return round((target - entry) / entry * 100.0, 2)
    return None


def _fallback_rank_from_reports(report_dir: Path = REPORTS) -> dict[str, Any]:
    """Build a degraded rank from existing recommendation artifacts.

    This keeps the recommender from silently producing zero picks when the
    broader AI swing-hold rank file/module is absent. Rows are explicitly marked
    as fallback-sourced so they cannot be confused with a full-universe scan.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(candidate: Any, source: str, default_score: float) -> None:
        if isinstance(candidate, str):
            row = {"ticker": candidate}
        elif isinstance(candidate, dict):
            row = dict(candidate.get("source_candidate") or candidate)
        else:
            return
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not ticker or ticker in seen:
            return
        seen.add(ticker)
        score = (
            row.get("composite_score")
            or row.get("recommender_score")
            or row.get("conviction_score")
            or row.get("score")
            or default_score
        )
        fallback = {
            **row,
            "ticker": ticker,
            "composite_score": _round(score, 2) or default_score,
            "last_close": _round(row.get("last_close") or row.get("close") or _candidate_entry(row), 4),
            "target_upside_pct": _candidate_upside(row),
            "reward_risk": _candidate_reward_risk(row),
            "setup": row.get("setup") or "fallback_candidate",
            "_fallback_rank_source": source,
        }
        rows.append(fallback)

    for name in ("recommendations.json", "forecast-recommendations-latest.json", "smart-recommendations.json"):
        data = _json(report_dir / name, {})
        for row in data.get("picks") or []:
            add(row, name, 60.0)

    super_smart = _json(report_dir / "super-smart-recommendations.json", {})
    for row in super_smart.get("picks") or []:
        add(row, "super-smart-recommendations.json", 55.0)
    for symbol in super_smart.get("strict_current_picks") or []:
        add(symbol, "super-smart-recommendations.json:strict_current_picks", 55.0)

    quick = _json(report_dir / "quick-3stock-backtest-latest.json", {})
    quick_symbols = (
        (quick.get("best_detail") or {}).get("current_top3_by_same_score_as_of_latest_date")
        or (quick.get("best") or {}).get("current_top3_by_same_score_as_of_latest_date")
        or []
    )
    for symbol in quick_symbols:
        add(symbol, "quick-3stock-backtest-latest.json", 50.0)

    rows.sort(key=lambda r: float(r.get("composite_score") or 0.0), reverse=True)
    return {
        "mode": "fallback_existing_recommendation_rank",
        "latest_price_date": None,
        "universe_count": len(rows),
        "top": rows[:40],
        "all": rows,
        "degraded_input": True,
        "input_warning": "ai-swing-hold rank was missing; used existing recommendation artifacts only.",
    }


def _load_or_build_rank(top: int) -> dict[str, Any]:
    path = REPORTS / "ai-swing-hold-rank.json"
    if not path.exists():
        try:
            from scripts.ai_swing_hold_rank import main as rank_main
            rank_main(["--top", str(max(top, 40))])
        except Exception:
            pass
    rank = _json(path, {"top": [], "all": []})
    if not (rank.get("all") or rank.get("top")):
        return _fallback_rank_from_reports(REPORTS)
    return rank


def _row_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(r.get("ticker", "")).upper(): r for r in (report.get("rows") or []) if r.get("ticker")}


def build_recommender_audit(candidate_tickers: list[str] | None = None) -> dict[str, Any]:
    tickers = candidate_tickers or []
    if not tickers:
        rank = _load_or_build_rank(40)
        tickers = [r["ticker"] for r in (rank.get("top") or [])[:40] if r.get("ticker")]
    cov = _knowledge_coverage(tickers)
    try:
        from scripts.pit_coverage import compute_pit_coverage
        pit = compute_pit_coverage()
    except Exception:
        pit = {"status": "unknown", "has_vendor_pit_universe": False, "delisted_included_pct": 0.0}
    gaps = summarize_capability_gaps(
        universe_count=_universe_count(),
        price_ticker_count=_price_ticker_count(),
        has_point_in_time_universe=bool(pit.get("has_vendor_pit_universe")),
        delisted_included_pct=float(pit.get("delisted_included_pct") or 0),
        forward_paper_trades=int(cov.get("forward_paper_trades") or 0),
        analyst_target_records=int(cov.get("analyst_target_records") or 0),
        fresh_fundamental_ticker_pct=float(cov.get("fresh_fundamental_ticker_pct") or 0),
        fresh_news_ticker_pct=float(cov.get("fresh_news_ticker_pct") or 0),
        social_ticker_pct=float(cov.get("social_ticker_pct") or 0),
        pit_status=str(pit.get("status") or "unknown"),
        forward_paper_observations=int(cov.get("forward_paper_observations") or 0),
        forward_paper_resolved=int(cov.get("forward_paper_resolved") or 0),
    )
    critical = [g for g in gaps if g["severity"] == "critical"]
    high = [g for g in gaps if g["severity"] == "high"]
    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "verdict": "research_only" if critical or high else "improving",
        "capability_score": max(0, round(100 - 18 * len(critical) - 9 * len(high) - 4 * sum(1 for g in gaps if g["severity"] == "medium"), 1)),
        "gaps": gaps,
        "coverage": {k: v for k, v in cov.items() if k != "per_ticker"},
        "pit_coverage": pit,
        "disclaimer": DISCLAIMER,
    }


def build_super_smart_recommendations(top: int = 20, refresh: bool = False) -> dict[str, Any]:
    if refresh or not (REPORTS / "ai-swing-hold-rank.json").exists():
        try:
            from scripts.ai_swing_hold_rank import main as rank_main
            rank_main(["--top", str(max(top, 40))])
        except Exception:
            pass
    rank = _load_or_build_rank(max(top, 40))
    base = (rank.get("all") or rank.get("top") or [])[: max(top * 3, 40)]
    tickers = [str(r.get("ticker", "")).upper() for r in base if r.get("ticker")]
    strict = _json(Path("/tmp/tb_strict_recommend.json"), {})
    if not strict:
        try:
            from scripts.recommend import recommend
            strict = recommend(equity=50000, top=10)
        except Exception:
            strict = {}
    strict_set = {str(p.get("ticker", "")).upper() for p in strict.get("picks", [])}

    macro = _json(REPORTS / "macro-context-latest.json", {})
    if not macro:
        try:
            from scripts.macro_context import build_macro_context
            macro = build_macro_context(horizon_days=7)
        except Exception:
            macro = {"macro_risk": "unknown"}

    top_tickers = tickers[: max(top, 25)]
    try:
        from scripts.outlier_context import build_outlier_context
        outlier = build_outlier_context(top_tickers)
    except Exception:
        outlier = _json(REPORTS / "outlier-context-latest.json", {})
    try:
        from scripts.target_quality import build_target_quality_context
        tq = build_target_quality_context(top_tickers)
    except Exception:
        tq = _json(REPORTS / "target-quality-latest.json", {})

    out_by = _row_map(outlier)
    tq_by = _row_map(tq)
    cov = _knowledge_coverage(tickers)
    scored = []
    for c in base:
        t = str(c.get("ticker", "")).upper()
        overlays = {
            "strict_pick": t in strict_set,
            "outlier": out_by.get(t, {}),
            "target_quality": tq_by.get(t, {}),
            "macro_risk": macro.get("macro_risk", "unknown"),
            "evidence": (cov.get("per_ticker") or {}).get(t, {}),
        }
        scored.append(score_candidate_intelligence(c, overlays))
    scored.sort(key=lambda r: r["recommender_score"], reverse=True)

    audit = build_recommender_audit(tickers)
    picks = scored[:top]
    payload = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "mode": "super_smart_research_recommender_v1",
        "latest_price_date": rank.get("latest_price_date"),
        "universe_scanned": rank.get("universe_count") or _universe_count(),
        "strict_current_picks": sorted(strict_set),
        "macro_context": {"macro_risk": macro.get("macro_risk"), "stance": macro.get("stance"), "upcoming_events": macro.get("upcoming_events", [])[:3]},
        "audit": audit,
        "picks": picks,
        "what_i_was_lacking_and_built": [
            "Added a self-auditing recommender layer that states data/intelligence gaps before ranking.",
            "Added candidate-level confidence ceilings so missing evidence cannot masquerade as high conviction.",
            "Blended strict TradingBrain picks, 3-year pattern rank, macro, outlier, target-quality, catalyst/news, fundamentals, and social coverage.",
            "Kept outputs research-only with explicit red-team risks and evidence gaps per ticker.",
        ],
        "disclaimer": DISCLAIMER,
    }
    (REPORTS / "super-smart-recommendations.json").write_text(json.dumps(payload, indent=2, default=str))
    (REPORTS / "super-smart-recommendations.md").write_text(_markdown(payload))
    return payload


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# TradingBrain Super-Smart US Stock Recommender",
        "",
        f"Generated: {payload.get('asof')}",
        f"Latest price date: {payload.get('latest_price_date')}",
        f"Universe scanned: {payload.get('universe_scanned')}",
        f"Capability verdict: {payload.get('audit', {}).get('verdict')} · score {payload.get('audit', {}).get('capability_score')}/100",
        "",
        "## Top research candidates",
    ]
    for i, r in enumerate(payload.get("picks", []), 1):
        lines.append("")
        lines.append(f"{i}. {r['ticker']} — score {r['recommender_score']} · {r['action_label']} · ceiling {r['confidence_ceiling']}")
        lines.append(f"   Close: {r.get('last_close')} · setup: {r.get('setup')} · upside: {r.get('modeled_upside_pct')}% · RR: {r.get('reward_risk')}")
        lines.append(f"   Why: {'; '.join(r.get('why_it_scores', [])[:3])}")
        if r.get("evidence_gaps"):
            lines.append(f"   Gaps: {'; '.join(r['evidence_gaps'][:3])}")
        lines.append(f"   Red team: {'; '.join(r.get('red_team_risks', [])[:2])}")
    lines.extend(["", "## Biggest remaining engine gaps"])
    for g in payload.get("audit", {}).get("gaps", []):
        if g.get("severity") != "ok":
            lines.append(f"- {g['id']} ({g['severity']}): {g['evidence']} — {g['build_next']}")
    lines.extend(["", payload.get("disclaimer", DISCLAIMER)])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = build_super_smart_recommendations(top=args.top, refresh=args.refresh)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"Super-smart recommender: {len(out['picks'])} candidates · capability {out['audit']['capability_score']}/100 · {out['audit']['verdict']}")
        for i, r in enumerate(out["picks"][: args.top], 1):
            print(f"{i:2d}. {r['ticker']:5s} score={r['recommender_score']:4.1f} {r['action_label']:<24s} ceiling={r['confidence_ceiling']:<8s} close={r.get('last_close')}")
        print(f"Wrote {REPORTS / 'super-smart-recommendations.json'}")
        print(f"Wrote {REPORTS / 'super-smart-recommendations.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
