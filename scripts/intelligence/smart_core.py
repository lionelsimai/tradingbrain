"""Adaptive Intelligence Core — orchestration.

Composes regime adaptation + uncertainty fusion + outcome calibration into a
single enriched read for one candidate, WITHOUT mutating the base engine. The
canonical raw conviction comes from `scripts.recommend.score_pillars`; this layer
only:
  * tilts the *positive* alpha-pillar contributions by regime,
  * discounts conviction for cross-pillar disagreement,
  * recalibrates against the realized track record (Bayesian / reliability),
  * preserves the honest moderate cap unless LIVE evidence lifts it,
  * emits a size THROTTLE (<= 1.0) that can only reduce risk.

Returns a dict the recommender merges into its pick. Pure given its inputs.
"""
from __future__ import annotations

from . import MODERATE_CAP, regime_adaptive, uncertainty, pillars, relative_strength

# alpha pillars that regime tilts apply to (regime pillar is the gate, untouched)
_ALPHA = ("trend", "momentum", "sentiment")


def _band(score: float) -> str:
    if score >= 75:
        return "strong"
    if score >= 55:
        return "moderate"
    if score >= 40:
        return "weak"
    return "pass"


def score_smart(c: dict, regime: dict, raw_score: float, missing: list[str],
                calibrator, outcomes, *, lib: dict | None = None,
                x_sentiment: dict | None = None, social_sentiment: dict | None = None,
                live_n: int = 0, atr_pct: float | None = None,
                vix: float | None = None, peer_rs: dict | None = None) -> dict:
    """Enrich a base conviction with adaptive intelligence.

    raw_score/missing are the canonical outputs of recommend.score_pillars.
    Returns a dict of new fields (non-destructive) to merge into the pick.
    """
    setup = c.get("setup", "")
    profile = regime_adaptive.regime_profile(regime)
    mults = regime_adaptive.pillar_multipliers(profile)
    pts = pillars.pillar_points(c, regime, lib or {}, x_sentiment, social_sentiment)

    # 1) Regime tilt — only re-weight POSITIVE alpha contributions (never amplify
    #    a penalty, never invent edge). delta = (mult-1) * max(0, pts).
    tilt_delta = 0.0
    tilt_detail = {}
    for p in _ALPHA:
        base_pts = pts.get(p, 0.0)
        mult = float(mults.get(p, 1.0))
        d = (mult - 1.0) * max(0.0, base_pts)
        if abs(d) > 1e-9:
            tilt_detail[p] = round(d, 2)
        tilt_delta += d
    # 1b) Peer/sector relative strength — bounded stock-specific edge (or no-op).
    prs_delta = relative_strength.conviction_points(peer_rs)
    regime_adjusted = max(0.0, min(100.0, raw_score + tilt_delta + prs_delta))

    # 2) Uncertainty — discount for disagreement among signed pillar votes.
    vote_pts = {k: pts.get(k, 0.0) for k in ("trend", "momentum", "sentiment", "regime")}
    if abs(prs_delta) > 1e-9:
        vote_pts["peer_rs"] = prs_delta
    unc = uncertainty.fuse(vote_pts, regime_adjusted, n_missing=len(missing or []))

    # 3) Calibration against realized outcomes (Bayesian / reliability curve).
    evidence = outcomes.setup_evidence(setup)
    cal = calibrator.calibrate(regime_adjusted, setup, evidence)

    # Compose: calibrated score, minus the disagreement penalty.
    smart = cal["calibrated_score"] - unc["penalty"]
    smart = max(0.0, min(100.0, smart))

    # 4) Honest cap — nothing is lifted above MODERATE_CAP unless LIVE evidence
    #    earns it. This preserves the system's core honesty invariant.
    cap_active = (live_n == 0) and not cal["lifts_cap"]
    if cap_active:
        smart = min(smart, float(MODERATE_CAP))

    # 5) Size throttle — combines regime exposure + volatility targeting. <= 1.0.
    throttle = regime_adaptive.size_throttle(profile, atr_pct=atr_pct, vix=vix)

    notes = []
    if tilt_detail:
        notes.append(
            f"regime tilt ({profile['raw_label']}): "
            + ", ".join(f"{k} {v:+.1f}" for k, v in tilt_detail.items()))
    if abs(prs_delta) > 1e-9 and peer_rs:
        notes.append(
            f"peer RS {prs_delta:+.1f} (vs {peer_rs.get('sector','sector')} peers, "
            f"rank {peer_rs.get('sector_rank', 0):.0%})")
    if unc["penalty"] > 0:
        notes.append(f"uncertainty -{unc['penalty']:.1f} ({unc['note']}, agreement {unc['agreement']})")
    if evidence["source"] != "none":
        notes.append(
            f"calibrated on {evidence['n']} {evidence['source']} trades "
            f"(p_win {cal['p_win']:.0%}, exp {cal['expected_R']:+.2f}R)"
            + ("; reliability curve" if cal["reliability_used"] else ""))
    if cap_active:
        notes.append(f"capped at {MODERATE_CAP} (no live track record yet)")
    if throttle["throttle"] < 1.0:
        notes.append(f"size throttled x{throttle['throttle']:.2f} ({profile['raw_label']} regime)")

    return {
        "smart_conviction": round(smart, 1),
        "smart_band": _band(smart),
        "base_conviction": round(float(raw_score), 1),
        "regime_adjusted": round(regime_adjusted, 1),
        "conviction_interval": unc["interval"],
        "p_win": cal["p_win"],
        "expected_R": cal["expected_R"],
        "evidence_source": evidence["source"],
        "evidence_n": evidence["n"],
        "lifts_cap": cal["lifts_cap"],
        "cap_active": cap_active,
        "pillar_agreement": unc["agreement"],
        "peer_rs": peer_rs or None,
        "size_throttle": throttle["throttle"],
        "size_throttle_detail": throttle,
        "regime_profile": {k: profile[k] for k in ("raw_label", "stable", "exposure", "hostility")},
        "intelligence_notes": notes,
    }
