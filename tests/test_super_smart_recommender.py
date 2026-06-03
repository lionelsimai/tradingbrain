from __future__ import annotations

import json

import duckdb

from scripts import super_smart_recommender as ssr
from scripts.super_smart_recommender import (
    summarize_capability_gaps,
    score_candidate_intelligence,
)


def test_capability_audit_surfaces_specific_missing_layers():
    gaps = summarize_capability_gaps(
        universe_count=77,
        price_ticker_count=81,
        has_point_in_time_universe=False,
        delisted_included_pct=0,
        forward_paper_trades=0,
        analyst_target_records=0,
        fresh_fundamental_ticker_pct=0.35,
        fresh_news_ticker_pct=0.42,
        social_ticker_pct=0.25,
    )

    by_id = {g["id"]: g for g in gaps}

    assert by_id["universe_breadth"]["severity"] in {"high", "critical"}
    assert by_id["point_in_time_survivorship"]["severity"] == "critical"
    assert by_id["forward_paper_evidence"]["severity"] == "critical"
    assert by_id["analyst_target_provenance"]["severity"] == "high"
    assert "build_next" in by_id["fresh_fundamental_catalyst_coverage"]


def test_score_candidate_keeps_strict_pick_but_caps_missing_evidence():
    candidate = {
        "ticker": "MU",
        "sector": "memory_storage",
        "composite_score": 87.2,
        "return_3y_pct": 1371.0,
        "return_1y_pct": 909.6,
        "return_6m_pct": 332.5,
        "return_3m_pct": 55.0,
        "rel_1y_vs_qqq_pct": 867.0,
        "max_drawdown_3y_pct": -57.8,
        "target_upside_pct": 26.7,
        "setup": "MOMO_CONT",
        "reward_risk": 2.0,
    }
    overlays = {
        "strict_pick": True,
        "outlier": {"risk_level": "low", "veto": False, "flags": []},
        "target_quality": {
            "verdict": "usable_but_discount_confidence",
            "confidence_adjustment": "reduce one notch",
            "cautions": ["No analyst-target provenance data; do not treat external/banker price targets as reliable."],
        },
        "macro_risk": "low",
        "evidence": {"recent_documents_14d": 2, "social_available": True, "fundamentals_available": True},
    }

    scored = score_candidate_intelligence(candidate, overlays)

    assert scored["ticker"] == "MU"
    assert scored["recommender_score"] >= 75
    assert scored["confidence_ceiling"] == "moderate"
    assert any("analyst-target provenance" in gap for gap in scored["evidence_gaps"])
    assert any("strict TradingBrain" in reason for reason in scored["why_it_scores"])


def test_score_candidate_vetoes_high_outlier_risk():
    candidate = {"ticker": "DELL", "composite_score": 72, "return_1y_pct": 270, "max_drawdown_3y_pct": -60}
    scored = score_candidate_intelligence(candidate, {"outlier": {"risk_level": "high", "veto": True}, "macro_risk": "low"})

    assert scored["action_label"] == "avoid_until_review"
    assert scored["recommender_score"] < 60
    assert any("outlier" in risk.lower() for risk in scored["red_team_risks"])


def test_knowledge_coverage_counts_optional_forward_and_target_tables_without_fact_tables(tmp_path, monkeypatch):
    kb = tmp_path / "knowledge.duckdb"
    con = duckdb.connect(str(kb))
    con.execute("CREATE TABLE forward_paper_observations(ticker VARCHAR, status VARCHAR, realized_R DOUBLE)")
    con.execute("INSERT INTO forward_paper_observations VALUES ('MU', 'resolved', 1.2), ('NVDA', 'pending', NULL)")
    con.execute("CREATE TABLE analyst_targets(ticker VARCHAR, broker VARCHAR, target DOUBLE)")
    con.execute("INSERT INTO analyst_targets VALUES ('MU', 'Example Securities', 110.0)")
    con.close()

    monkeypatch.setattr(ssr, "KB", kb)

    cov = ssr._knowledge_coverage(["MU", "NVDA"])

    assert cov["forward_paper_observations"] == 2
    assert cov["forward_paper_resolved"] == 1
    assert cov["analyst_target_records"] == 1
    assert cov["per_ticker"]["MU"]["fundamentals_available"] is False
    assert cov["per_ticker"]["NVDA"]["recent_documents_14d"] == 0


def test_rank_loader_falls_back_to_existing_recommendations_when_rank_missing(tmp_path, monkeypatch):
    rec = {
        "picks": [{
            "ticker": "MU",
            "conviction_score": 60,
            "entry_zone": {"low": 100.0, "high": 100.0},
            "stop_loss": 90.0,
            "targets": [{"level": 130.0}],
            "reward_to_risk": 3.0,
        }]
    }
    (tmp_path / "recommendations.json").write_text(json.dumps(rec))
    monkeypatch.setattr(ssr, "REPORTS", tmp_path)

    rank = ssr._load_or_build_rank(10)

    assert rank["mode"] == "fallback_existing_recommendation_rank"
    assert rank["degraded_input"] is True
    assert rank["all"][0]["ticker"] == "MU"
    assert rank["all"][0]["target_upside_pct"] == 30.0
    assert rank["all"][0]["reward_risk"] == 3.0
