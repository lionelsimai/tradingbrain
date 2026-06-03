"""Regime-adaptive intelligence — pure, deterministic, no look-ahead.

Consumes the *causal* regime the brain already computes (scripts/brain/hmm_regime.py
writes reports/hmm-regime.json with acted_label/stability/target_exposure) and turns
it into two things:

  * pillar weight multipliers — tilt the alpha pillars by regime (lean into trend
    in a stable bull, fade momentum/sentiment and favour quality in a bear).
  * a position-size THROTTLE in [floor, 1.0] — combines the regime's target
    exposure with volatility targeting. It is clamped to <= 1.0 by construction,
    so applying it can only REDUCE size; it can never push past the existing
    fail-closed risk caps. This is the safety-preserving way to add adaptivity.

Nothing here reads the future: the regime is point-in-time and the volatility
input is the trailing ATR%.
"""
from __future__ import annotations

# Canonical regime labels the brain emits (HMM: Crash/Bear/Neutral/Bull/Euphoria;
# rules engine: bull/bear/chop/high_vol_*/crash). We normalise both.
_HOSTILE = {"bear", "crash", "high_vol_bear"}
_CAUTION = {"chop", "neutral", "high_vol_bull", "euphoria", "correction", "mixed"}
_RISK_ON = {"bull"}

# Default target exposure by normalised label when the regime file omits it.
_EXPOSURE = {
    "crash": 0.10,
    "bear": 0.30,
    "high_vol_bear": 0.30,
    "chop": 0.55,
    "neutral": 0.60,
    "high_vol_bull": 0.65,
    "euphoria": 0.60,
    "mixed": 0.60,
    "correction": 0.45,
    "bull": 0.90,
    "unknown": 0.50,
}


def _norm_label(label: str | None) -> str:
    return str(label or "unknown").strip().lower().replace(" ", "_").replace("-", "_")


def regime_profile(regime: dict | None) -> dict:
    """Normalise a regime dict into a small, stable profile.

    Returns: {label, raw_label, stable, risk_on, hostile, exposure, hostility}.
    `hostility` in [0,1] (0 = supportive, 1 = crash); `exposure` in [0,1].
    """
    regime = regime or {}
    raw = regime.get("acted_label") or regime.get("raw_label") or regime.get("label") or "Unknown"
    label = _norm_label(raw)
    stable = str(regime.get("stability", "")).upper() == "STABLE"

    exposure = regime.get("target_exposure")
    try:
        exposure = float(exposure)
    except (TypeError, ValueError):
        exposure = _EXPOSURE.get(label, 0.5)
    exposure = max(0.0, min(1.0, exposure))

    if label in _HOSTILE:
        hostility = 1.0 if label == "crash" else 0.7
        if label == "high_vol_bear":
            hostility = 0.6
    elif label in _CAUTION:
        hostility = 0.4 if label in ("euphoria", "high_vol_bull") else 0.3
    elif label in _RISK_ON:
        hostility = 0.1 if stable else 0.2
    else:
        hostility = 0.5  # unknown -> neutral caution

    return {
        "label": label,
        "raw_label": raw,
        "stable": stable,
        "risk_on": label in _RISK_ON,
        "hostile": label in _HOSTILE,
        "exposure": exposure,
        "hostility": round(hostility, 3),
    }


# Pillar tilts by regime. Keys are the *alpha* pillars (the regime pillar itself
# is the risk gate and is NOT re-weighted — it already carries its own sign).
# Conservative, hand-set, documented; never invent edge, only redistribute it.
def pillar_multipliers(profile: dict) -> dict:
    """Return {pillar: multiplier} for trend/momentum/sentiment/fundamental.

    Bull (stable): lean into trend & momentum. Bear/Crash: fade momentum &
    sentiment hard, favour fundamentals/quality. Caution: mild fade.
    """
    label = profile.get("label", "unknown")
    stable = profile.get("stable", False)

    if label == "bull":
        m = {"trend": 1.15 if stable else 1.05, "momentum": 1.10 if stable else 1.0,
             "sentiment": 1.0, "fundamental": 0.95}
    elif label in ("neutral", "chop", "mixed", "correction"):
        m = {"trend": 1.0, "momentum": 0.90, "sentiment": 0.90, "fundamental": 1.10}
    elif label in ("euphoria", "high_vol_bull"):
        # late-cycle: momentum is chase-risk, sentiment is unreliable, favour quality
        m = {"trend": 1.0, "momentum": 0.80, "sentiment": 0.80, "fundamental": 1.15}
    elif label in _HOSTILE:
        m = {"trend": 0.60, "momentum": 0.50, "sentiment": 0.60, "fundamental": 1.25}
    else:  # unknown
        m = {"trend": 0.90, "momentum": 0.85, "sentiment": 0.85, "fundamental": 1.05}
    return m


def size_throttle(profile: dict, atr_pct: float | None = None,
                  target_atr_pct: float = 2.0, vix: float | None = None,
                  floor: float = 0.25) -> dict:
    """A position-size multiplier in [floor, 1.0]. ALWAYS <= 1.0.

    Combines three reducers (each <= 1.0):
      * regime factor  = target exposure (so a bear/crash regime shrinks size).
      * vol factor     = min(1, target_atr_pct / atr_pct) — bigger ATR -> smaller.
      * vix factor     = 1 / 0.8 / 0.6 as VIX crosses 22 / 30.

    Returns a dict with the components for transparency plus `throttle`.
    """
    regime_factor = max(0.0, min(1.0, float(profile.get("exposure", 0.5))))

    if atr_pct is None or atr_pct <= 0:
        vol_factor = 1.0
    else:
        # Only ever reduce: when realised vol exceeds the target, scale down.
        vol_factor = min(1.0, float(target_atr_pct) / float(atr_pct))

    if vix is None:
        vix_factor = 1.0
    elif vix > 30:
        vix_factor = 0.6
    elif vix > 22:
        vix_factor = 0.8
    else:
        vix_factor = 1.0

    throttle = regime_factor * vol_factor * vix_factor
    throttle = max(floor, min(1.0, throttle))
    return {
        "throttle": round(throttle, 4),
        "regime_factor": round(regime_factor, 4),
        "vol_factor": round(vol_factor, 4),
        "vix_factor": round(vix_factor, 4),
        "floor": floor,
    }
