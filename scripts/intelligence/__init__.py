"""TradingBrain — Adaptive Intelligence Core.

A composable *overlay* that makes the brain smarter without touching the honest
base engine (`scripts/recommend.py`) or the fail-closed risk path (`safety/`).

Three reinforcing capabilities, all deterministic and offline:

  * regime_adaptive — tilt the pillar weights and *throttle* position size by the
    causal market regime (the throttle is always <= 1.0, so it can only REDUCE
    risk, never lift it past the existing caps).
  * uncertainty     — fuse the pillars with explicit disagreement accounting, so
    conflicting signals lower usable conviction instead of being averaged away.
  * conviction_calibration — learn a conviction -> outcome mapping from the REAL
    track record (live evidence separated from replay), with Bayesian shrinkage
    so small samples are not over-trusted. Fail-closed: with no evidence it is a
    no-op and the honest "capped at moderate until live trades" rule still holds.

Design laws (inherited from DOCTRINE.md and enforced by tests):
  1. Never lift the moderate conviction cap on anything but LIVE evidence.
  2. The size throttle can only reduce size (it is clamped to <= 1.0).
  3. No look-ahead: regime is causal, evidence is realized/past, RS is trailing.
  4. Degrade honestly: missing data => the overlay returns to base behaviour.
"""
from __future__ import annotations

# Honest ceiling while there is no live track record. Mirrors
# scripts.recommend.MODERATE_CAP; re-declared here so the package is importable
# stand-alone, and asserted equal in the tests.
MODERATE_CAP = 60

__all__ = ["MODERATE_CAP"]
