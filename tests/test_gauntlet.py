#!/usr/bin/env python3
"""Tests for the institutional gauntlet + extended Monte Carlo.

Checks the maths is sane and the verdict is honest (cannot be APPROVED while the
system has zero live trades — Phase K is a required gate)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lab import gauntlet
from backtest import monte_carlo


def test_monte_carlo_has_risk_of_ruin_and_streaks():
    rep = monte_carlo.run(paths=3000, source="replay", seed=3, method="block")
    if "error" in rep:
        return
    assert "risk_of_ruin" in rep and 0 <= rep["risk_of_ruin"]["probability"] <= 1
    ls = rep["longest_losing_streak"]
    assert ls["p50"] <= ls["p95"] <= ls["worst"]
    assert 0 <= rep["time_to_recovery_trades"]["recovered_fraction"] <= 1


def test_pbo_in_range():
    df = gauntlet._ledger()
    p = gauntlet.pbo(df)
    if p["value_pct"] is not None:
        assert 0 <= p["value_pct"] <= 100


def test_deflated_sharpe_is_probability():
    df = gauntlet._ledger()
    d = gauntlet.deflated_sharpe(df)
    assert 0.0 <= d["deflated_sharpe_prob"] <= 1.0


def test_kelly_used_below_full_kelly():
    df = gauntlet._ledger()
    k = gauntlet.kelly(df, risk_pct=0.5)
    if k.get("kelly_fraction") and k["kelly_fraction"] > 0:
        assert k["risk_per_trade_used"] < k["kelly_fraction"]  # never over-bet full Kelly


def test_verdict_never_approved_without_live_trades():
    """The central safety property: no APPROVED verdict on a system that has
    never traded live (Phase K is required)."""
    r = gauntlet.scorecard()
    live_n = (gauntlet._report("scorecard-replay.json").get("overall_live") or {}).get("n", 0) or 0
    if live_n == 0:
        assert r["verdict"] == "REJECTED"
    assert 0 <= r["overall_score"] <= 100


def test_scorecard_has_all_dimensions():
    r = gauntlet.scorecard()
    assert len(r["scorecard_0_100"]) >= 10  # the spec's robustness dimensions
