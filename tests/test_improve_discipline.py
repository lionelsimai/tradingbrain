"""Teeth for the self-improvement loop (loops/improve.py).

These checks are the discipline that distinguishes a learning *system* from a
learning *log*: it must (a) FLAG goals the evidence doesn't support, (b) REFUSE to
score replay/backtest as if it were live, and (c) demand real fills before tuning.
That discipline was previously untested — so it could silently regress. It can't now.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from loops import improve


def test_goal_realism_flags_a_goal_the_evidence_cannot_support():
    # high Sharpe + market-beating CAGR + "beat QQQ on total return" — all things
    # the system's own backtest showed it does NOT do.
    warnings = improve.goal_realism({"success": {
        "min_sharpe": 1.5, "min_cagr_pct": 20, "beat_qqq_total_return": True}})
    assert warnings, "an evidence-unsupported goal MUST be flagged, not chased"
    assert len(warnings) >= 2


def test_goal_realism_passes_a_realistic_goal():
    warnings = improve.goal_realism({"success": {"min_sharpe": 0.5, "min_cagr_pct": 6}})
    assert warnings == [], warnings


def test_score_refuses_to_score_replay_as_if_it_were_live():
    # 0 true live fills => must be INSUFFICIENT_DATA, never scored against the goal.
    out = improve.score_live({"success": {"min_live_trades": 50}}, {})
    assert out["status"] == "INSUFFICIENT_DATA"
    assert out["live_n"] == 0


def test_propose_change_demands_real_fills_before_tuning():
    change = improve.propose_change(
        {"success": {"min_live_trades": 50}}, {}, {}, [], [])
    assert change["variable"] == "data_mode"
    assert "paper" in change["proposed_value"].lower()
