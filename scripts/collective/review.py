#!/usr/bin/env python3
"""Independent adversarial review: Red Team + Risk Officer (DOCTRINE v3 §4).

These NEVER develop strategies; they only attack/judge. The Orchestrator may
not deploy anything they veto without explicit resolution. Both read the
research-report.json + calibration produced by the research engine.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
RESEARCH = ROOT / "reports" / "research-report.json"

def _load():
    return json.loads(RESEARCH.read_text()) if RESEARCH.exists() else {}

def red_team(setup: str) -> dict:
    """Build the strongest case the edge is an illusion. Returns findings + verdict."""
    r = _load()
    s = r.get("strategies", {}).get(setup, {})
    findings, severity = [], 0
    # 1. Survivorship / data integrity
    if not r.get("survivorship_free", False):
        findings.append("Survivorship bias: universe excludes delisted names — live edge likely lower.")
        severity += 1
    # 2. Walk-forward efficiency (overfit detector)
    wfe = s.get("walk_forward_efficiency")
    if wfe is not None and (wfe < 0.5 or wfe < 0):
        findings.append(f"Walk-forward efficiency {wfe}: OOS is a poor fraction of IS — overfit risk.")
        severity += 2
    # 3. Outlier dependence (trade-removal)
    tr = s.get("trade_removal", {})
    if tr and tr.get("expectancy_ex_top") is not None:
        full = s.get("full", {}).get("expectancy_R", 0)
        if full and tr["expectancy_ex_top"] < 0.5 * full:
            findings.append("Edge collapses when top trades removed — rests on a few lucky outliers.")
            severity += 2
    # 4. Regime dependence
    byr = s.get("by_regime", {})
    pos = [k for k,v in byr.items() if isinstance(v,dict) and v.get("expectancy_R",0) > 0]
    neg = [k for k,v in byr.items() if isinstance(v,dict) and v.get("expectancy_R",0) <= 0]
    if byr and len(pos) <= 1:
        findings.append(f"Edge concentrated in one regime ({pos}); hidden regime bet.")
        severity += 2
    elif neg:
        findings.append(f"Negative expectancy in regimes: {neg} — gate these off.")
    # 5. Significance
    ci = s.get("bootstrap_ci_expectancy_R")
    if ci and ci[0] <= 0:
        findings.append(f"Bootstrap CI {ci} includes zero — edge not statistically clear.")
        severity += 2
    ds = s.get("deflated_sharpe")
    if ds is not None and ds < 0.1:
        findings.append(f"Deflated Sharpe {ds} ~ 0 after multiple-testing discount.")
        severity += 1
    verdict = "SURVIVES" if severity <= 1 else ("WOUNDED" if severity <= 3 else "KILLED")
    if not findings:
        findings.append("No fatal flaw found in the standard attack battery.")
    return {"agent": "red_team", "setup": setup, "severity": severity,
            "verdict": verdict, "findings": findings}

def risk_officer(setup: str, session: dict | None = None) -> dict:
    """Judge whether the setup can be sized within risk law. Veto if not."""
    r = _load()
    s = r.get("strategies", {}).get(setup, {})
    objections, ok = [], True
    full = s.get("full", {})
    # Per-signal compounded DD is not portfolio DD, but flag extreme tails.
    mc = s.get("monte_carlo_dd", {})
    if mc.get("p95_drawdown_pct") is not None and mc["p95_drawdown_pct"] < -50:
        objections.append(f"Monte-Carlo p95 drawdown {mc['p95_drawdown_pct']}% — size must stay small; cap heat.")
    exp = full.get("expectancy_R", 0)
    if exp <= 0:
        objections.append(f"Non-positive expectancy ({exp}R) — VETO live deployment.")
        ok = False
    n = full.get("n_trades", 0)
    if n < 100:
        objections.append(f"Only {n} trades — insufficient sample for full size; provisional only.")
    verdict = "APPROVED" if ok and not objections else ("CONDITIONAL" if ok else "VETO")
    if not objections:
        objections.append("Within risk law: positive expectancy, adequate sample. Size per session risk%.")
    return {"agent": "risk_officer", "setup": setup, "verdict": verdict, "objections": objections}

if __name__ == "__main__":
    import sys
    setup = sys.argv[1] if len(sys.argv) > 1 else "MEAN_REVERSION"
    print(json.dumps(red_team(setup), indent=2))
    print(json.dumps(risk_officer(setup), indent=2))
