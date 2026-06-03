#!/usr/bin/env python3
"""Shared calibration loader — the brain's trained parameters.

Reads reports/calibration.json (produced by backtest/stress_test.py) and
exposes helpers the live engine uses to weight setup confidence, gate
low/negative-edge setups, and tilt position size by regime.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
CALIB = ROOT / "reports" / "calibration.json"
RESEARCH = ROOT / "reports" / "research-report.json"
GAUNTLET = ROOT / "reports" / "gauntlet.json"

# Regimes where LONG swing setups have historically negative expectancy.
# From the 10y stress test: 2018/2020/2022 all bled. Hard-gate longs here.
BEAR_REGIMES = {"bear", "crash"}

# Live setups without their own backtest sample inherit a proxy's calibration.
SETUP_ALIAS = {"MOMO_CONT": "TREND_LEADER"}

def _resolve(setup: str) -> str:
    return SETUP_ALIAS.get(setup, setup)

_cache = None

def load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CALIB.read_text()).get("calibration", {})
        except Exception:
            _cache = {}
    return _cache

def setup_stats(setup: str) -> dict:
    return load().get(_resolve(setup), {})

def _find_pbo(obj):
    """Locate the PBO verdict object (has both 'pass' and 'value_pct') wherever it
    is nested. In the current gauntlet it lives at checks -> pbo."""
    if isinstance(obj, dict):
        if isinstance(obj.get("pass"), bool) and "value_pct" in obj:
            return obj
        for v in obj.values():
            r = _find_pbo(v)
            if r is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_pbo(v)
            if r is not None:
                return r
    return None

def portfolio_pbo_pass() -> bool | None:
    """The gauntlet's PBO verdict (probability of backtest overfitting): True if it
    PASSED (low PBO), False if it FAILED (high PBO => setup SELECTION is overfit,
    worse than random), None if not computed yet. PBO lives at gauntlet.json ->
    checks -> pbo (with a robust fallback search)."""
    try:
        d = json.loads(GAUNTLET.read_text())
    except Exception:
        return None
    pbo = (d.get("checks") or {}).get("pbo") if isinstance(d, dict) else None
    if not isinstance(pbo, dict):
        pbo = _find_pbo(d)
    return pbo["pass"] if isinstance(pbo, dict) and isinstance(pbo.get("pass"), bool) else None

def is_enabled(setup: str) -> bool:
    # FIX-4 (P0-2): a FAILING portfolio PBO means setup SELECTION is overfit
    # (worse than random) — so gate EVERY setup off. The honest number must GATE,
    # not just be computed and ignored. Fail-open only when PBO is absent.
    if portfolio_pbo_pass() is False:
        return False
    s = load().get(_resolve(setup))
    # default-enabled if no calibration yet (graceful before first stress test)
    return True if not s else bool(s.get("enabled", True))

def oos_expectancy(setup: str) -> float:
    return float(load().get(_resolve(setup), {}).get("oos_expectancy_R", 0.0))

def regime_multiplier(setup: str, regime: str) -> float:
    s = load().get(_resolve(setup), {})
    rm = s.get("regime_multiplier", {})
    mult = float(rm.get(regime, 1.0))
    # Never size UP into a risk-off regime. A >1.0 multiplier learned for a
    # bear/correction/high-vol regime is a survivorship-bias artifact (the few
    # winners that worked in weakness), not a reason to lean in. Clamp to <=1.0.
    risk_off = any(k in (regime or "").lower()
                   for k in ("bear", "correction", "volatile", "risk_off", "risk-off", "high_vol"))
    if risk_off:
        mult = min(mult, 1.0)
    return mult

def confidence_weight(setup: str, regime: str) -> float:
    """0..1.5 weight to scale a setup's base score by proven edge × regime fit."""
    exp = oos_expectancy(setup)
    if exp <= 0:
        return 0.0
    # map OOS expectancy 0..1.0R → 0.4..1.2, then apply regime multiplier
    base = 0.4 + min(exp, 1.0) * 0.8
    return round(min(1.5, base * regime_multiplier(setup, regime)), 3)

def long_gated(regime: str) -> bool:
    """True if long swing setups should be suppressed in this regime."""
    return regime.lower() in BEAR_REGIMES


# ---- Research Engine verdicts (DOCTRINE Part XII: trade only survivors) ----
_research = None

def load_research() -> dict:
    """Return {setup: verdict} from the research engine report."""
    global _research
    if _research is None:
        try:
            data = json.loads(RESEARCH.read_text()).get("strategies", {})
            _research = {k: v.get("verdict", "Unknown") for k, v in data.items()}
        except Exception:
            _research = {}
    return _research

def research_verdict(setup: str) -> str:
    return load_research().get(_resolve(setup), "Unknown")

def size_cap(setup: str) -> float:
    """Fraction of full size allowed by research verdict.
    Deploy=1.0 (validated), Iterate=0.5 (provisional), Reject=0.0, Unknown=1.0 (graceful)."""
    return {"Deploy": 1.0, "Iterate": 0.5, "Reject": 0.0, "Unknown": 1.0}[research_verdict(setup)]


# ---- Scorecard source governance (Section 15): evidence is SEPARATED by source.
# replay  -> may only SUPPRESS a bleeding setup (conservative), never promote.
# live    -> the only source allowed to drive a LIVE gate; needs real fills.
# paper   -> forward evidence; never drives the live gate.
_scorecards: dict = {}

def load_scorecard(source: str = "replay") -> dict:
    """Per-setup realized stats from a SPECIFIC evidence source. No mixing."""
    if source not in _scorecards:
        data = {}
        f = ROOT / "reports" / f"scorecard-{source}.json"
        if not f.exists() and source == "replay":
            f = ROOT / "reports" / "live-scorecard.json"   # legacy replay file
        try:
            data = json.loads(f.read_text()).get("by_setup", {})
        except Exception:
            data = {}
        _scorecards[source] = data
    return _scorecards[source]

def live_expectancy(setup: str):
    """Replay-realized expectancy — DISPLAY/suppression only, not a live edge."""
    s = load_scorecard("replay").get(_resolve(setup)) or load_scorecard("replay").get(setup)
    return s.get("expectancy_R") if s else None

def replay_negative_gated(setup: str, min_n: int = 25) -> bool:
    """True if REPLAY realized expectancy is negative over a meaningful sample.
    Replay may ONLY suppress (conservative) — it can never enable or up-size."""
    s = load_scorecard("replay").get(_resolve(setup)) or load_scorecard("replay").get(setup)
    if not s or s.get("n", 0) < min_n:
        return False
    return s.get("expectancy_R", 0) < -0.05

def live_gated(setup: str, min_n: int = 30) -> bool:
    """True only if LIVE (broker-confirmed) realized expectancy is negative over a
    meaningful LIVE sample. Replay/paper are NEVER used here. With no live fills
    yet this returns False (there is no live evidence to gate on)."""
    s = load_scorecard("live").get(_resolve(setup)) or load_scorecard("live").get(setup)
    if not s or s.get("n", 0) < min_n:
        return False
    return s.get("expectancy_R", 0) < -0.05
