"""Conviction calibration — the brain learning what its scores actually mean.

Turns a raw 0-100 conviction into a *probability-grounded* read using the real
track record, with two layers:

  1. Reliability curve (auto-activates later): if a per-pick ledger of
     (raw_score, realized_R) samples exists, fit a monotonic isotonic mapping
     (pool-adjacent-violators) raw_score -> empirical win-rate. This is the
     proper calibration curve. Today the forward-paper ledger is empty, so this
     layer is dormant and the calibrator is fail-closed.

  2. Setup evidence with Bayesian shrinkage (active now): combine the setup's
     realized win-rate / expectancy with a Beta-Binomial prior centred on the
     universe base rate, so a 28-sample setup is trusted, a 3-sample one is not.

Honesty laws enforced here and in tests:
  * Only LIVE evidence (source == 'live', n >= MIN_LIVE_N) sets lifts_cap=True.
    Replay evidence can refine the read but can NEVER lift the moderate cap.
  * With no evidence the calibrator is a no-op: calibrated_score == raw_score,
    lifts_cap=False.
"""
from __future__ import annotations

from .outcomes import MIN_LIVE_N

# Strength of the Beta prior (in pseudo-trades). Higher => shrink small samples
# harder toward the base rate. 12 means a 12-trade setup is half-trusted.
PRIOR_STRENGTH = 12.0
# How many conviction points one R of shrunk edge is worth.
R_TO_POINTS = 22.0


def _pav_isotonic(xs: list[float], ys: list[float]) -> list[tuple[float, float]]:
    """Pool-adjacent-violators isotonic regression. Returns (x, fitted_y) knots,
    monotone non-decreasing in y. xs assumed sorted ascending."""
    # blocks of (sum_y, weight, x_right)
    blocks: list[list[float]] = []
    for x, y in zip(xs, ys):
        blocks.append([y, 1.0, x])
        while len(blocks) >= 2 and blocks[-2][0] / blocks[-2][1] > blocks[-1][0] / blocks[-1][1]:
            sy, w, xr = blocks.pop()
            blocks[-1][0] += sy
            blocks[-1][1] += w
            blocks[-1][2] = xr
    out = []
    for sy, w, xr in blocks:
        out.append((xr, sy / w))
    return out


class Calibrator:
    """Maps (raw_score, setup, evidence) -> calibrated read. Fail-closed."""

    def __init__(self, base_rate: float = 0.5, live_n: int = 0,
                 reliability_knots: list[tuple[float, float]] | None = None):
        self.base_rate = max(0.05, min(0.95, float(base_rate)))
        self.live_n = int(live_n)
        self.reliability_knots = reliability_knots or []

    # ----- reliability curve (layer 1) -----
    @classmethod
    def from_samples(cls, samples: list[tuple[float, float]], base_rate: float = 0.5,
                     live_n: int = 0, min_samples: int = 30) -> "Calibrator":
        """Fit a reliability curve from (raw_score, realized_R) samples.

        A win is realized_R > 0. Below min_samples the curve is left empty
        (dormant) and only the Bayesian-evidence layer is used.
        """
        clean = [(float(s), 1.0 if float(r) > 0 else 0.0)
                 for s, r in samples if s is not None and r is not None]
        knots = None
        if len(clean) >= min_samples:
            clean.sort(key=lambda t: t[0])
            xs = [c[0] for c in clean]
            ys = [c[1] for c in clean]
            knots = _pav_isotonic(xs, ys)
        return cls(base_rate=base_rate, live_n=live_n, reliability_knots=knots or [])

    def _reliability_p(self, raw: float) -> float | None:
        if not self.reliability_knots:
            return None
        # piecewise-constant lookup on the monotone knots
        p = self.reliability_knots[0][1]
        for x_right, val in self.reliability_knots:
            if raw <= x_right:
                return val
            p = val
        return p

    # ----- Bayesian setup evidence (layer 2) -----
    def _shrink(self, evidence: dict) -> dict:
        n = int(evidence.get("n", 0) or 0)
        if n <= 0 or evidence.get("p_win") is None:
            return {"p_win": self.base_rate, "expected_R": 0.0, "n": 0}
        p_obs = float(evidence["p_win"])
        wins = p_obs * n
        # Beta-Binomial posterior mean centred on base_rate with PRIOR_STRENGTH.
        a0 = self.base_rate * PRIOR_STRENGTH
        b0 = (1.0 - self.base_rate) * PRIOR_STRENGTH
        p_win = (wins + a0) / (n + a0 + b0)
        # Expected R shrunk toward 0 by sample size.
        exp_obs = float(evidence.get("expectancy_R", 0.0) or 0.0)
        expected_R = (n * exp_obs) / (n + PRIOR_STRENGTH)
        return {"p_win": p_win, "expected_R": expected_R, "n": n}

    def calibrate(self, raw_score: float, setup: str, evidence: dict) -> dict:
        """Return a calibrated read for one candidate.

        Keys: calibrated_score (0-100), p_win (0-1), expected_R, source,
              lifts_cap (bool), reliability_used (bool), n.
        """
        raw = max(0.0, min(100.0, float(raw_score)))
        source = str(evidence.get("source", "none"))
        shr = self._shrink(evidence)

        rel_p = self._reliability_p(raw)
        reliability_used = rel_p is not None
        if reliability_used:
            # Trust the empirical reliability curve directly (probability scale).
            p_win = rel_p
            calibrated = 100.0 * p_win
        else:
            p_win = shr["p_win"]
            # Nudge the raw score by the shrunk edge (in R) -> conviction points.
            calibrated = raw + R_TO_POINTS * shr["expected_R"]

        calibrated = max(0.0, min(100.0, calibrated))
        # ONLY genuine LIVE setup evidence (sufficiently sampled) may lift the moderate
        # cap. A reliability curve refines the SCORE but can never independently lift
        # the cap — it may have been fit on replay/paper, which must never count as live.
        lifts_cap = (source == "live" and int(evidence.get("n", 0) or 0) >= MIN_LIVE_N)

        return {
            "calibrated_score": round(calibrated, 1),
            "p_win": round(float(p_win), 4),
            "expected_R": round(float(shr["expected_R"]), 4),
            "source": source,
            "n": int(shr["n"]),
            "lifts_cap": bool(lifts_cap),
            "reliability_used": bool(reliability_used),
        }


def load(reports_dir, outcomes=None) -> Calibrator:
    """Build a Calibrator from the reports dir. Reads any per-pick reliability
    ledger if present (reports/conviction-outcomes.json: list of
    {raw_score, realized_R}); otherwise the reliability layer stays dormant."""
    from pathlib import Path
    import json
    from . import outcomes as outcomes_mod

    reports_dir = Path(reports_dir)
    oc = outcomes if outcomes is not None else outcomes_mod.load(reports_dir)

    samples: list[tuple[float, float]] = []
    ledger = reports_dir / "conviction-outcomes.json"
    if ledger.exists():
        try:
            rows = json.loads(ledger.read_text())
            rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
            for r in rows:
                s, rr = r.get("raw_score"), r.get("realized_R")
                if s is not None and rr is not None:
                    samples.append((float(s), float(rr)))
        except Exception:
            samples = []

    if samples:
        return Calibrator.from_samples(samples, base_rate=oc.base_rate, live_n=oc.live_n)
    return Calibrator(base_rate=oc.base_rate, live_n=oc.live_n)
