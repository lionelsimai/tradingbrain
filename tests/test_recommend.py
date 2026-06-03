#!/usr/bin/env python3
"""Tests for the recommendation engine — the honesty invariants that matter.

  * Never recommends a setup marked Broken.
  * Conviction is capped at moderate while there are zero live trades (no pick
    can be 'strong' on replay/survivorship-biased data).
  * Every emitted pick has a stop, a reward:risk at/above the configured minimum,
    a single invalidation, and caveats — the schema the front end relies on.
  * Emits a valid structured pick when given a genuinely strong candidate.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import recommend


def test_no_strong_band_while_zero_live_trades():
    rep = recommend.recommend(equity=50000, top=5)
    if rep["live_trades_on_record"] == 0:
        assert rep["conviction_cap_active"] is True
        for p in rep["picks"]:
            assert p["conviction_score"] <= recommend.MODERATE_CAP
            assert p["conviction_band"] != "strong"


def test_every_pick_has_defined_risk():
    rep = recommend.recommend(equity=50000, top=5)
    minrr = rep["min_reward_risk"]
    for p in rep["picks"]:
        assert p["stop_loss"] > 0
        assert p["reward_to_risk"] >= minrr
        assert p["invalidation"]
        assert p["confidence_caveats"]
        assert p["position_size"]["shares_or_units"] > 0


def test_broken_setups_never_recommended():
    rep = recommend.recommend(equity=50000, top=10)
    # BREAKOUT is 'Broken' in strategy_library; it must not appear as a pick.
    for p in rep["picks"]:
        # a pick must not be a setup the library flags Broken
        lib, _ = recommend._setup_history()
        broken = {k for k, v in lib.items() if v.get("status") == "Broken"}
        # we don't store setup on the pick dict directly; assert via thesis text
        for b in broken:
            assert not p["thesis"].startswith(f"{b} setup"), f"recommended Broken setup {b}"


def test_emits_structured_pick_for_strong_candidate(monkeypatch):
    """Given a clean, high-R:R, non-overbought candidate in a bull regime, the
    engine should surface a moderate pick with the full schema."""
    strong = {"setup": "TREND_LEADER", "ticker": "TEST", "rsi": 60, "rs20": 50,
              "entry": 100.0, "stop": 95.0, "target": 115.0,
              "reason": "clean breakout retest", "r_multiple": 3.0,
              "close": 100.0}
    monkeypatch.setattr(recommend, "_json",
                        lambda name, default=None: (
                            {"candidates": [strong], "asof": "2026-05-30"} if name == "swing-setups.json"
                            else {"acted_label": "Bull", "stability": "STABLE", "target_exposure": 0.9}
                            if name == "hmm-regime.json" else (default or {})))
    rep = recommend.recommend(equity=50000, top=3)
    assert not rep["no_qualifying_setups"], "a clean 3:1 bull setup should qualify"
    p = rep["picks"][0]
    assert p["ticker"] == "TEST" and p["reward_to_risk"] >= 2.0
    assert p["conviction_band"] in ("moderate", "weak")  # capped, never strong
