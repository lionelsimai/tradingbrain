from loops import forward_paper_runner


def test_forward_paper_scorecard_exposes_horizon_metrics(tmp_path):
    card = forward_paper_runner.scorecard(tmp_path)

    for key in (
        "resolved_trades",
        "win_rate",
        "average_R",
        "median_R",
        "expectancy_R",
        "max_drawdown_R",
        "max_consecutive_losses",
        "strategy_breakdown",
        "regime_breakdown",
        "drift_status",
        "demotion_recommendations",
    ):
        assert key in card
    assert card["drift_status"] == "insufficient_forward_paper"
