#!/usr/bin/env python3
"""Tests for the Adaptive Intelligence Core overlay.

The invariants that MUST hold (they encode the system's honesty + safety):
  * The moderate conviction cap is never lifted on anything but LIVE evidence.
  * The size throttle is always <= 1.0 (it can only reduce risk).
  * No-evidence => the calibrator is a no-op (calibrated == raw).
  * Disagreeing pillars reduce conviction; a hostile regime reduces it further.
  * Everything degrades without crashing on empty inputs.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from scripts.intelligence import (
    MODERATE_CAP, regime_adaptive, uncertainty, outcomes as outcomes_mod,
    conviction_calibration as cc, smart_core,
)
import recommend


# --------------------------------------------------------------- constants --
def test_moderate_cap_matches_base_engine():
    assert MODERATE_CAP == recommend.MODERATE_CAP


# ------------------------------------------------------------ regime layer --
def test_size_throttle_never_exceeds_one():
    for label in ("Bull", "Bear", "Crash", "Neutral", "Euphoria", "Unknown"):
        for exp in (None, 0.0, 0.3, 0.9, 1.0, 2.0):
            prof = regime_adaptive.regime_profile({"acted_label": label, "target_exposure": exp})
            for atr in (None, 0.0, 0.5, 2.0, 8.0):
                for vix in (None, 12, 25, 40):
                    t = regime_adaptive.size_throttle(prof, atr_pct=atr, vix=vix)["throttle"]
                    assert 0.0 < t <= 1.0, (label, exp, atr, vix, t)


def test_low_vol_never_increases_size():
    # Very low ATR must NOT push the throttle above 1.0 (no leverage creep).
    prof = regime_adaptive.regime_profile({"acted_label": "Bull", "target_exposure": 1.0})
    assert regime_adaptive.size_throttle(prof, atr_pct=0.1)["throttle"] <= 1.0


def test_hostile_regime_throttles_harder_than_bull():
    bull = regime_adaptive.regime_profile({"acted_label": "Bull", "stability": "STABLE"})
    bear = regime_adaptive.regime_profile({"acted_label": "Bear", "stability": "STABLE"})
    assert regime_adaptive.size_throttle(bear)["throttle"] < regime_adaptive.size_throttle(bull)["throttle"]


def test_bull_tilts_trend_up_bear_fades_momentum():
    bull = regime_adaptive.pillar_multipliers(regime_adaptive.regime_profile(
        {"acted_label": "Bull", "stability": "STABLE"}))
    bear = regime_adaptive.pillar_multipliers(regime_adaptive.regime_profile(
        {"acted_label": "Bear"}))
    assert bull["trend"] > 1.0
    assert bear["momentum"] < 1.0


# ------------------------------------------------------------ uncertainty --
def test_unanimous_pillars_low_penalty():
    agree = uncertainty.fuse({"trend": 25, "momentum": 20, "regime": 25}, raw_score=60)
    conflict = uncertainty.fuse({"trend": 25, "momentum": 20, "regime": -25}, raw_score=60)
    assert agree["agreement"] == 1.0
    assert conflict["agreement"] < 1.0
    assert conflict["penalty"] > agree["penalty"]


def test_no_votes_is_uncertain():
    u = uncertainty.fuse({"trend": 0, "momentum": 0}, raw_score=50, n_missing=3)
    assert u["penalty"] > 0
    assert u["interval"][0] < 50 < u["interval"][1]


# ------------------------------------------------------------- calibrator --
def test_calibrator_no_evidence_is_noop():
    cal = cc.Calibrator(base_rate=0.5, live_n=0)
    out = cal.calibrate(58.0, "BREAKOUT", {"n": 0, "p_win": None, "source": "none"})
    assert out["calibrated_score"] == 58.0
    assert out["lifts_cap"] is False


def test_replay_evidence_never_lifts_cap():
    cal = cc.Calibrator(base_rate=0.5, live_n=0)
    ev = {"n": 28, "p_win": 0.75, "expectancy_R": 0.37, "source": "replay"}
    out = cal.calibrate(58.0, "BREAKOUT", ev)
    assert out["lifts_cap"] is False  # replay can refine but never lift


def test_live_evidence_can_lift_cap():
    cal = cc.Calibrator(base_rate=0.5, live_n=40)
    ev = {"n": 30, "p_win": 0.65, "expectancy_R": 0.4, "source": "live"}
    out = cal.calibrate(58.0, "BREAKOUT", ev)
    assert out["lifts_cap"] is True


def test_bayesian_shrinkage_pulls_small_samples_to_base():
    cal = cc.Calibrator(base_rate=0.5, live_n=0)
    big = cal.calibrate(60, "A", {"n": 200, "p_win": 0.9, "expectancy_R": 0.5, "source": "replay"})
    small = cal.calibrate(60, "B", {"n": 3, "p_win": 0.9, "expectancy_R": 0.5, "source": "replay"})
    # the 3-sample 90% win rate is shrunk much closer to the 0.5 base rate
    assert small["p_win"] < big["p_win"]
    assert abs(small["p_win"] - 0.5) < abs(big["p_win"] - 0.5)


def test_reliability_curve_is_monotone():
    # higher raw scores must map to >= win probability after isotonic fit
    samples = [(s, 1.0 if (s + (i % 5) * 4) > 55 else -1.0)
               for i, s in enumerate([20, 30, 40, 50, 60, 70, 80, 90] * 6)]
    cal = cc.Calibrator.from_samples(samples, base_rate=0.5, min_samples=20)
    ps = [cal.calibrate(s, "X", {"n": 0, "source": "none"})["p_win"] for s in (20, 40, 60, 80)]
    assert ps == sorted(ps)  # non-decreasing


# ------------------------------------------------- smart_core integration --
class _NullCal:
    def calibrate(self, raw, setup, ev):
        return {"calibrated_score": float(raw), "p_win": 0.5, "expected_R": 0.0,
                "source": ev.get("source", "none"), "n": 0, "lifts_cap": False,
                "reliability_used": False}


class _Outcomes:
    def __init__(self, ev): self._ev = ev
    def setup_evidence(self, setup): return self._ev


_STRONG = {"ticker": "NVDA", "setup": "BREAKOUT", "rsi": 60, "rs20": 30,
           "entry": 100, "stop": 95, "target": 115}


def test_honesty_cap_holds_with_replay_evidence_and_zero_live():
    ev = {"n": 28, "p_win": 0.75, "expectancy_R": 0.37, "source": "replay"}
    out = smart_core.score_smart(
        _STRONG, {"acted_label": "Bull", "stability": "STABLE"}, raw_score=95, missing=[],
        calibrator=cc.Calibrator(base_rate=0.5, live_n=0), outcomes=_Outcomes(ev), live_n=0)
    assert out["smart_conviction"] <= MODERATE_CAP
    assert out["cap_active"] is True


def test_live_evidence_allows_exceeding_cap():
    ev = {"n": 40, "p_win": 0.7, "expectancy_R": 0.6, "source": "live"}
    out = smart_core.score_smart(
        _STRONG, {"acted_label": "Bull", "stability": "STABLE"}, raw_score=90, missing=[],
        calibrator=cc.Calibrator(base_rate=0.5, live_n=40), outcomes=_Outcomes(ev), live_n=40)
    assert out["cap_active"] is False
    assert out["smart_conviction"] > MODERATE_CAP


def test_smart_throttle_and_bear_below_bull():
    ev = {"n": 0, "source": "none"}
    common = dict(raw_score=80, missing=[], calibrator=_NullCal(), outcomes=_Outcomes(ev), live_n=0)
    bull = smart_core.score_smart(_STRONG, {"acted_label": "Bull", "stability": "STABLE"}, **common)
    bear = smart_core.score_smart(_STRONG, {"acted_label": "Bear", "stability": "STABLE"}, **common)
    assert bull["size_throttle"] <= 1.0 and bear["size_throttle"] <= 1.0
    assert bear["size_throttle"] < bull["size_throttle"]
    # bear fades the alpha pillars -> lower (or equal, both capped) conviction
    assert bear["regime_adjusted"] <= bull["regime_adjusted"]


def test_degrades_on_empty_inputs():
    out = smart_core.score_smart(
        {}, {}, raw_score=0, missing=["trend", "momentum", "volume", "fundamental_catalyst"],
        calibrator=_NullCal(), outcomes=_Outcomes({"n": 0, "source": "none"}), live_n=0)
    assert 0 <= out["smart_conviction"] <= 100
    assert out["size_throttle"] <= 1.0
