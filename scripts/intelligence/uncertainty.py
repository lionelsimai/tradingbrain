"""Uncertainty-aware pillar fusion — pure, deterministic.

The base engine adds pillar points independently. That hides *disagreement*: a
+25 trend and a -25 regime average to a confident-looking middle. This module
treats the pillars as noisy votes and quantifies how much they agree, returning:

  * agreement       — share of signed alpha pillars pointing the same way (0..1).
  * dispersion      — spread of the pillar contributions (normalised 0..1).
  * missing_widen   — how much missing pillars widen the interval.
  * penalty         — conviction points to SUBTRACT when signals conflict or the
                      picture is thin (honest: be less sure when unsure).
  * interval        — [lo, hi] credible band around the raw conviction.

It never adds conviction; it can only widen the band and apply a penalty.
"""
from __future__ import annotations

import math


def fuse(pillar_points: dict, raw_score: float, n_missing: int = 0,
         max_penalty: float = 12.0) -> dict:
    """Fuse signed alpha-pillar contributions into an uncertainty read.

    pillar_points: {pillar_name: signed_points} for the ALPHA pillars
        (e.g. trend, momentum, sentiment, regime). Zeros are treated as
        "no vote" and excluded from the agreement calculation.
    raw_score: the 0-100 conviction the interval is centred on.
    n_missing: number of disclosed-missing pillars (widens the band).
    """
    votes = [float(v) for v in pillar_points.values() if abs(float(v)) > 1e-9]
    n = len(votes)

    if n == 0:
        # No directional votes at all — maximally uncertain.
        half = 18.0 + 4.0 * n_missing
        return {
            "agreement": 0.0,
            "dispersion": 1.0,
            "n_votes": 0,
            "n_missing": n_missing,
            "penalty": round(min(max_penalty, 6.0 + 2.0 * n_missing), 2),
            "interval": [max(0.0, raw_score - half), min(100.0, raw_score + half)],
            "note": "no directional pillar votes — conviction is structurally uncertain",
        }

    pos = sum(1 for v in votes if v > 0)
    neg = sum(1 for v in votes if v < 0)
    agreement = max(pos, neg) / n  # 1.0 = unanimous, 0.5 = split

    mean = sum(votes) / n
    var = sum((v - mean) ** 2 for v in votes) / n
    std = math.sqrt(var)
    # Normalise dispersion by a reference scale (~25 pts is a full pillar).
    dispersion = min(1.0, std / 25.0)

    # Penalty grows as agreement falls below unanimity and as data thins out.
    disagree = 1.0 - agreement
    penalty = max_penalty * (0.7 * disagree + 0.3 * dispersion)
    penalty += 1.5 * n_missing
    penalty = min(max_penalty + 6.0, penalty)

    # Interval half-width: base + disagreement + missing.
    half = 6.0 + 18.0 * disagree + 8.0 * dispersion + 3.0 * n_missing
    lo = max(0.0, raw_score - half)
    hi = min(100.0, raw_score + half)

    return {
        "agreement": round(agreement, 3),
        "dispersion": round(dispersion, 3),
        "n_votes": n,
        "n_missing": n_missing,
        "penalty": round(penalty, 2),
        "interval": [round(lo, 1), round(hi, 1)],
        "note": (
            "pillars broadly agree" if agreement >= 0.8 else
            "pillars partly conflict — conviction discounted" if agreement >= 0.55 else
            "pillars conflict materially — conviction heavily discounted"
        ),
    }
