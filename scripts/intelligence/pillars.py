"""Per-pillar point breakdown — mirrors scripts/recommend.score_pillars thresholds.

The base engine returns only the *summed* raw conviction. The intelligence
overlay needs the per-pillar contributions to (a) apply regime tilts to the
alpha pillars and (b) measure cross-pillar agreement. This module recomputes the
same deterministic point contributions from the same candidate fields, WITHOUT
mutating the base engine. The canonical raw conviction still comes from
recommend.score_pillars; these points are only used for deltas and agreement.
"""
from __future__ import annotations


def pillar_points(c: dict, regime: dict, lib: dict | None = None,
                  x_sentiment: dict | None = None,
                  social_sentiment: dict | None = None) -> dict:
    """Signed point contribution per alpha/risk pillar. Matches recommend.py."""
    lib = lib or {}
    rsi = c.get("rsi")
    rs20 = c.get("rs20")
    setup = c.get("setup", "")
    pts: dict[str, float] = {}

    # Trend & structure (+25 / +12 / 0)
    if rs20 is not None and rs20 > 20:
        pts["trend"] = 25.0
    elif rs20 is not None and rs20 > 0:
        pts["trend"] = 12.0
    else:
        pts["trend"] = 0.0

    # Momentum (+20 / +8 / -8 / 0)
    if rsi is not None:
        if 50 <= rsi <= 70:
            pts["momentum"] = 20.0
        elif 70 < rsi <= 80:
            pts["momentum"] = 8.0
        elif rsi > 80:
            pts["momentum"] = -8.0
        else:
            pts["momentum"] = 0.0
    else:
        pts["momentum"] = 0.0

    # Sentiment (bounded small, manipulation-aware) — approximate recommend.py
    tkr = str(c.get("ticker", "")).upper()
    ss = (social_sentiment or {}).get(tkr, {})
    xs = (x_sentiment or {}).get(tkr, {})
    sent = 0.0
    if ss and not ss.get("stale"):
        if float(ss.get("manipulation_risk", 0.0) or 0.0) < 0.45:
            sent = float(max(-8, min(8, int(ss.get("conviction_points", 0) or 0))))
            if abs(sent) < 1e-9 and xs:
                xc = float(xs.get("composite", 0.0) or 0.0)
                if abs(xc) >= 0.25:
                    sent = (1 if xc > 0 else -1) * min(10, max(3, int(abs(xc) * 12)))
    elif xs:
        xc = float(xs.get("composite", 0.0) or 0.0)
        if xc >= 0.25:
            sent = min(10, max(3, int(xc * 12)))
        elif xc <= -0.25:
            sent = -min(10, max(3, int(abs(xc) * 12)))
    pts["sentiment"] = float(sent)

    # Regime (risk gate) — directional, NOT re-weighted by tilts (+25 / +10 / -25)
    rlabel = regime.get("acted_label") or regime.get("raw_label") or "Unknown"
    stable = regime.get("stability") == "STABLE"
    if rlabel in ("Bull",) and stable:
        pts["regime"] = 25.0
    elif rlabel in ("Neutral", "Euphoria"):
        pts["regime"] = 10.0
    elif rlabel in ("Bear", "Crash"):
        pts["regime"] = -25.0
    else:
        pts["regime"] = 0.0

    # Setup replay prior (bounded small)
    exp = (lib.get(setup) or {}).get("oos_expectancy_R")
    if exp is not None:
        pts["setup_prior"] = float(max(-8, min(10, int(exp * 6))))
    return pts
