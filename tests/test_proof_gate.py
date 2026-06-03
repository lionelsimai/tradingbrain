from __future__ import annotations

from scripts.proof_gate import evaluate_proof_gate, render_markdown


def test_proof_gate_refuses_8_without_forward_horizon_outcomes_and_pit():
    world = {
        "overall_score": 65.6,
        "rating_1_to_10": 6.6,
        "verdict": "RESEARCH_ONLY",
        "hard_blockers": ["forward_paper_record", "survivorship_free_data"],
        "counts": {"forward_paper_observations": 28, "forward_paper_resolved": 0},
    }
    horizon = {
        "outcomes_total": 0,
        "decision_useful": False,
        "by_horizon": [],
    }
    gate = evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live={"verdict": "BLOCKED"})

    assert gate["proven_8_of_10"] is False
    assert gate["max_honest_rating"] <= 7.0
    assert "200+ resolved 1D/5D/20D horizon outcomes" in gate["missing_proof"]
    assert "survivorship/PIT blocker cleared" in gate["missing_proof"]
    assert gate["live_trading_proven"] is False
    assert "cannot fabricate time" in " ".join(gate["truth_constraints"]).lower()


def test_proof_gate_allows_8_when_forward_horizon_edge_and_pit_are_present():
    world = {
        "overall_score": 84.0,
        "rating_1_to_10": 8.4,
        "verdict": "IMPROVING",
        "hard_blockers": [],
        "counts": {"forward_paper_observations": 220, "forward_paper_resolved": 220},
    }
    horizon = {
        "outcomes_total": 660,
        "decision_useful": True,
        "by_horizon": [
            {"horizon_days": 1, "n": 220, "hit_rate_pct": 53.0, "avg_return_R": 0.08, "avg_max_drawdown_pct": -1.4},
            {"horizon_days": 5, "n": 220, "hit_rate_pct": 56.0, "avg_return_R": 0.22, "avg_max_drawdown_pct": -3.5},
            {"horizon_days": 20, "n": 220, "hit_rate_pct": 54.0, "avg_return_R": 0.35, "avg_max_drawdown_pct": -7.5},
        ],
        "benchmark_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 220, "excess_hit_rate_pct": 52.0, "avg_excess_return_R": 0.04},
            {"horizon_days": 5, "n": 220, "excess_hit_rate_pct": 54.0, "avg_excess_return_R": 0.12},
            {"horizon_days": 20, "n": 220, "excess_hit_rate_pct": 53.0, "avg_excess_return_R": 0.18},
        ],
        "slippage_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 220, "avg_slippage_adjusted_return_R": 0.03},
            {"horizon_days": 5, "n": 220, "avg_slippage_adjusted_return_R": 0.10},
            {"horizon_days": 20, "n": 220, "avg_slippage_adjusted_return_R": 0.15},
        ],
        "benchmark_adjusted_evidence_present": True,
    }
    gate = evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live={"verdict": "BLOCKED"})

    assert gate["proven_8_of_10"] is True
    assert gate["max_honest_rating"] >= 8.0
    assert gate["live_trading_proven"] is False
    assert gate["missing_proof"] == ["go-live gate cleared for any live-trading claim"]


def test_proof_gate_refuses_9_without_institutional_evidence_pack():
    world = {
        "overall_score": 89.0,
        "rating_1_to_10": 8.9,
        "verdict": "IMPROVING",
        "hard_blockers": [],
        "counts": {"forward_paper_observations": 500, "forward_paper_resolved": 500},
    }
    horizon = {
        "outcomes_total": 500,
        "decision_useful": True,
        "regime_count": 1,
        "by_horizon": [
            {"horizon_days": 1, "n": 170, "hit_rate_pct": 53.0, "avg_return_R": 0.08},
            {"horizon_days": 5, "n": 170, "hit_rate_pct": 56.0, "avg_return_R": 0.22},
            {"horizon_days": 20, "n": 160, "hit_rate_pct": 54.0, "avg_return_R": 0.35},
        ],
        "benchmark_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 170, "excess_hit_rate_pct": 52.0, "avg_excess_return_R": 0.04},
            {"horizon_days": 5, "n": 170, "excess_hit_rate_pct": 54.0, "avg_excess_return_R": 0.12},
            {"horizon_days": 20, "n": 160, "excess_hit_rate_pct": 53.0, "avg_excess_return_R": 0.18},
        ],
        "slippage_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 170, "avg_slippage_adjusted_return_R": 0.03},
            {"horizon_days": 5, "n": 170, "avg_slippage_adjusted_return_R": 0.10},
            {"horizon_days": 20, "n": 160, "avg_slippage_adjusted_return_R": 0.15},
        ],
        "benchmark_adjusted_evidence_present": True,
    }
    portfolio = {"institutional_risk_budget_ok": False, "portfolio_heat_pct": 2.0}
    gate = evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live={"verdict": "BLOCKED"}, portfolio_risk=portfolio)

    assert gate["proven_8_of_10"] is True
    assert gate["proven_9_of_10"] is False
    assert gate["max_honest_rating"] < 9.0
    assert "3+ forward market regimes" in gate["missing_9_proof"]
    assert "institutional portfolio risk budget passing" in gate["missing_9_proof"]


def test_proof_gate_next_actions_do_not_repeat_passed_portfolio_budget():
    world = {
        "overall_score": 84.0,
        "rating_1_to_10": 8.4,
        "verdict": "IMPROVING",
        "hard_blockers": ["survivorship_free_data", "forward_paper_record"],
        "counts": {"forward_paper_observations": 0, "forward_paper_resolved": 0},
    }
    gate = evaluate_proof_gate(
        world=world,
        horizon_scorecard={"outcomes_total": 0, "by_horizon": [], "decision_useful": False},
        go_live={"verdict": "BLOCKED"},
        portfolio_risk={"institutional_risk_budget_ok": True, "portfolio_heat_pct": 1.0},
        pit_coverage={"status": "open", "candidate_traceable_pct": 100.0},
    )

    assert "institutional portfolio risk budget passing" not in gate["missing_9_proof"]
    assert not any("portfolio risk-budget" in item for item in gate["required_next_evidence"])


def test_proof_gate_allows_9_only_with_deep_forward_pit_and_portfolio_evidence():
    world = {
        "overall_score": 91.0,
        "rating_1_to_10": 9.1,
        "verdict": "WORLD_CLASS_RESEARCH",
        "hard_blockers": [],
        "counts": {"forward_paper_observations": 720, "forward_paper_resolved": 720},
    }
    horizon = {
        "outcomes_total": 720,
        "decision_useful": True,
        "regime_count": 3,
        "by_horizon": [
            {"horizon_days": 1, "n": 240, "hit_rate_pct": 55.0, "avg_return_R": 0.10, "avg_max_drawdown_pct": -1.2},
            {"horizon_days": 5, "n": 240, "hit_rate_pct": 57.0, "avg_return_R": 0.24, "avg_max_drawdown_pct": -3.0},
            {"horizon_days": 20, "n": 240, "hit_rate_pct": 56.0, "avg_return_R": 0.42, "avg_max_drawdown_pct": -6.5},
        ],
        "benchmark_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 240, "excess_hit_rate_pct": 53.0, "avg_excess_return_R": 0.05},
            {"horizon_days": 5, "n": 240, "excess_hit_rate_pct": 55.0, "avg_excess_return_R": 0.15},
            {"horizon_days": 20, "n": 240, "excess_hit_rate_pct": 54.0, "avg_excess_return_R": 0.21},
        ],
        "slippage_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 240, "avg_slippage_adjusted_return_R": 0.04},
            {"horizon_days": 5, "n": 240, "avg_slippage_adjusted_return_R": 0.13},
            {"horizon_days": 20, "n": 240, "avg_slippage_adjusted_return_R": 0.19},
        ],
        "benchmark_adjusted_evidence_present": True,
    }
    portfolio = {"institutional_risk_budget_ok": True, "portfolio_heat_pct": 2.0, "max_position_risk_pct": 0.6}
    pit = {"status": "closed", "candidate_traceable_pct": 100.0, "candidate_coverage_status": "excellent"}
    gate = evaluate_proof_gate(
        world=world,
        horizon_scorecard=horizon,
        go_live={"verdict": "CLEARED FOR LIVE"},
        portfolio_risk=portfolio,
        pit_coverage=pit,
    )

    assert gate["proven_9_of_10"] is True
    assert gate["max_honest_rating"] >= 9.0
    assert gate["live_trading_proven"] is True


def test_proof_gate_markdown_is_plain_english_and_non_promotional():
    gate = evaluate_proof_gate(
        world={"overall_score": 65.6, "rating_1_to_10": 6.6, "verdict": "RESEARCH_ONLY", "hard_blockers": ["forward_paper_record"]},
        horizon_scorecard={"outcomes_total": 0, "by_horizon": []},
        go_live={"verdict": "BLOCKED"},
    )
    md = render_markdown(gate)
    assert "Proof Gate" in md
    assert "not financial advice" in md.lower()
    assert "PROVEN_8_OF_10" in md
    assert "NO" in md


def test_hermes_tool_exposes_proof_gate_status():
    from scripts.agent.hermes_tools import run_tool

    out = run_tool("get_tradingbrain_proof_gate", {})
    assert out["available"] is True
    assert "proven_8_of_10" in out
    assert "max_honest_rating" in out
    assert "reports" in out


def test_proof_gate_refuses_8_without_benchmark_adjusted_edge():
    world = {
        "overall_score": 84.0, "rating_1_to_10": 8.4, "verdict": "IMPROVING", "hard_blockers": [],
        "counts": {"forward_paper_observations": 220, "forward_paper_resolved": 220},
    }
    horizon = {
        "outcomes_total": 660, "decision_useful": True,
        "by_horizon": [
            {"horizon_days": 1, "n": 220, "hit_rate_pct": 53.0, "avg_return_R": 0.08},
            {"horizon_days": 5, "n": 220, "hit_rate_pct": 56.0, "avg_return_R": 0.22},
            {"horizon_days": 20, "n": 220, "hit_rate_pct": 54.0, "avg_return_R": 0.35},
        ],
    }
    gate = evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live={"verdict": "BLOCKED"})

    assert gate["proven_8_of_10"] is False
    assert gate["benchmark_edge_ok"] is False
    assert "1D benchmark-adjusted scorecard row" in gate["missing_proof"]


def test_proof_gate_refuses_8_when_slippage_adjusted_edge_is_negative():
    world = {
        "overall_score": 84.0,
        "rating_1_to_10": 8.4,
        "verdict": "IMPROVING",
        "hard_blockers": [],
        "counts": {"forward_paper_observations": 220, "forward_paper_resolved": 220},
    }
    horizon = {
        "outcomes_total": 660,
        "decision_useful": True,
        "by_horizon": [
            {"horizon_days": 1, "n": 220, "hit_rate_pct": 53.0, "avg_return_R": 0.08},
            {"horizon_days": 5, "n": 220, "hit_rate_pct": 56.0, "avg_return_R": 0.22},
            {"horizon_days": 20, "n": 220, "hit_rate_pct": 54.0, "avg_return_R": 0.35},
        ],
        "benchmark_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 220, "excess_hit_rate_pct": 52.0, "avg_excess_return_R": 0.04},
            {"horizon_days": 5, "n": 220, "excess_hit_rate_pct": 54.0, "avg_excess_return_R": 0.12},
            {"horizon_days": 20, "n": 220, "excess_hit_rate_pct": 53.0, "avg_excess_return_R": 0.18},
        ],
        "benchmark_adjusted_evidence_present": True,
        "slippage_adjusted_by_horizon": [
            {"horizon_days": 1, "n": 220, "avg_slippage_adjusted_return_R": -0.01},
            {"horizon_days": 5, "n": 220, "avg_slippage_adjusted_return_R": -0.03},
            {"horizon_days": 20, "n": 220, "avg_slippage_adjusted_return_R": -0.05},
        ],
    }
    gate = evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live={"verdict": "BLOCKED"})

    assert gate["proven_8_of_10"] is False
    assert gate["slippage_adjusted_edge_ok"] is False
    assert "1D slippage-adjusted average R >0" in gate["missing_proof"]
