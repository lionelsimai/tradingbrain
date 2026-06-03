#!/usr/bin/env python3
"""Go-Live Authority — spec Section 14 (the capstone gate).

This is the single check the master prompt demands: TradingBrain may risk real
capital ONLY when all seven gates are green. This reads the system's REAL
artifacts (not opinions), maps them to the seven gates, and renders one verdict.

It defaults to BLOCKED and stays blocked until every gate passes. It never
flips itself to live and it tells the plain truth about what is failing.

Gates (Section 14):
  1. Walk-forward OOS acceptable          <- reports/walk-forward.json
  2. Monte Carlo worst-case DD survivable <- reports/monte-carlo.json
  3. Stress scenarios survived            <- reports/stress-test.json (+ human)
  4. Overfitting checks cleared           <- walk-forward gap + reports/validate.json
  5. Paper == backtest in same range      <- reports/scorecard-paper.json only
  6. Risk controls + kill switch + data   <- risk-policy / circuit-breakers / data-quality / live-data-health / kill_switch
  7. Human reviewed & approved            <- config/go_live_signoff.yaml

Run:
  python3 -m lab.go_live          # verdict to console + reports/go-live.{json,md}
  python3 -m lab.go_live --json   # machine-readable
Exit code is non-zero while go-live is BLOCKED (so a pipeline can gate on it).
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT

REPORTS = ROOT / "reports"
CONFIG = ROOT / "config"
PASS, FAIL, MISSING, HUMAN = "PASS", "FAIL", "MISSING", "NEEDS_HUMAN"


def _load(name: str):
    p = REPORTS / name
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _goal():
    try:
        import yaml
        return yaml.safe_load((CONFIG / "goal.yaml").read_text()) or {}
    except Exception:
        return {}


def gate1_walk_forward(goal) -> dict:
    wf = _load("walk-forward.json")
    if not wf:
        return {"gate": "1. Walk-forward OOS", "status": MISSING,
                "detail": "reports/walk-forward.json absent — run backtest.walk_forward."}
    min_sharpe = goal.get("success", {}).get("min_sharpe", 0.5)
    oos = wf.get("median_oos_sharpe")
    nwin = wf.get("windows", 0) or 0
    beat = wf.get("windows_beating_spy", 0) or 0
    gap = wf.get("is_vs_oos_gap")
    ok = (oos is not None and oos >= min_sharpe and beat >= (nwin + 1) // 2)
    warn = ""
    if gap is not None and gap > 1.0:
        warn = (f" WARNING: in-sample beats OOS by {gap} Sharpe — sizeable, a "
                "soft sign of overfitting; have a human review window stability.")
    return {"gate": "1. Walk-forward OOS", "status": PASS if ok else FAIL,
            "detail": f"median OOS Sharpe {oos} (need >= {min_sharpe}); "
                      f"beats SPY in {beat}/{nwin} windows.{warn}"}


def gate2_monte_carlo(goal) -> dict:
    mc = _load("monte-carlo.json")
    if not mc or "error" in (mc or {}):
        return {"gate": "2. Monte Carlo worst-case drawdown", "status": MISSING,
                "detail": "reports/monte-carlo.json absent/insufficient — run backtest.monte_carlo."}
    ceiling = mc.get("drawdown_ceiling_pct", 20)
    p99 = mc.get("max_drawdown_pct_approx", {}).get("p99")
    breach = mc.get("prob_breach_ceiling", 1.0)
    src = mc.get("source")
    numeric_ok = (p99 is not None and p99 <= ceiling and breach <= 0.01)
    if not numeric_ok:
        return {"gate": "2. Monte Carlo worst-case drawdown", "status": FAIL,
                "detail": f"99th-pct drawdown ≈{p99}% vs ceiling {ceiling}%; "
                          f"P(breach)={breach}."}
    # numeric pass — but if it's replay-only, it cannot certify live behaviour
    if src != "live":
        return {"gate": "2. Monte Carlo worst-case drawdown", "status": HUMAN,
                "detail": f"Distribution survivable on {src} data (99th-pct DD ≈{p99}%, "
                          f"ceiling {ceiling}%), BUT it is resampled from replay "
                          "(survivorship-biased). Re-run on live fills before trusting."}
    return {"gate": "2. Monte Carlo worst-case drawdown", "status": PASS,
            "detail": f"99th-pct drawdown ≈{p99}% within {ceiling}% ceiling; P(breach)={breach}."}


def gate3_stress() -> dict:
    st = _load("stress-test.json")
    cb = _load("circuit-breakers.json")
    if not st:
        return {"gate": "3. Stress scenarios survived", "status": MISSING,
                "detail": "reports/stress-test.json absent — run backtest.stress_test."}
    windows = st.get("stress_windows", {}) or {}
    worst = None
    for name, w in windows.items():
        if isinstance(w, dict) and "expectancy_R" in w:
            if worst is None or w["expectancy_R"] < worst[1]:
                worst = (name, w["expectancy_R"], w.get("max_consec_losses"))
    breaker_ok = cb is not None and "sizing_scalar" in cb
    note = ("Crash windows are negative (expected for trend-following — the edge "
            "is being OUT, not long, in crashes). Automated stats cannot certify "
            "single-account survival through a compound crash, so this gate needs "
            "a human to confirm capital-intact + breakers fired.")
    detail = ""
    if worst:
        detail = f"Worst window: {worst[0]} expectancy {worst[1]:+.3f}R, " \
                 f"max consecutive losses {worst[2]}. "
    detail += ("Circuit-breaker system wired." if breaker_ok else
               "Circuit-breaker artifact missing. ") + " " + note
    return {"gate": "3. Stress scenarios survived",
            "status": HUMAN if breaker_ok else FAIL, "detail": detail}


def gate4_overfitting(goal) -> dict:
    wf = _load("walk-forward.json") or {}
    val = _load("validate.json")
    gap = wf.get("is_vs_oos_gap")
    # Hard threshold (F5): the in-sample/out-of-sample Sharpe gap is now a gate,
    # not a warning. Configurable; default 1.5. 1.69 (current) correctly FAILS.
    max_gap = float(goal.get("success", {}).get("max_is_oos_sharpe_gap", 1.5))
    gap_ok = gap is not None and gap <= max_gap
    if val is None:
        return {"gate": "4. Overfitting checks", "status": MISSING,
                "detail": "No-look-ahead / null-data PROOFS not on file — run "
                          "`python3 -m lab.validate` to populate reports/validate.json. "
                          f"(IS-vs-OOS gap {gap}, hard limit {max_gap}.)"}
    proofs_ok = bool(val.get("pass"))
    ok = proofs_ok and gap_ok
    why = []
    if not proofs_ok:
        why.append("look-ahead/null/determinism proofs FAILED")
    if not gap_ok:
        why.append(f"IS-vs-OOS Sharpe gap {gap} exceeds hard limit {max_gap} "
                   "(overfitting risk — OOS must hold up closer to in-sample)")
    return {"gate": "4. Overfitting checks", "status": PASS if ok else FAIL,
            "detail": (f"proofs pass; IS-vs-OOS gap {gap} within {max_gap}."
                       if ok else "; ".join(why))}


def gate5_paper() -> dict:
    sc = _load("scorecard-paper.json")
    if not sc:
        return {"gate": "5. Paper matches backtest", "status": MISSING,
                "detail": "reports/scorecard-paper.json absent — replay/backtest evidence "
                          "is not allowed to satisfy the paper gate."}
    raw_resolved = int(sc.get("resolved") or (sc.get("overall") or {}).get("n", 0) or 0)
    if "live_like_resolved_trades" in sc:
        n_live = int(sc.get("live_like_resolved_trades") or 0)
        evidence_note = (
            f"live-like paper fills: {n_live}; total paper resolved: {raw_resolved}. "
            "Synthetic or non-approved quote-source paper is excluded from this gate."
        )
    else:
        n_live = raw_resolved
        evidence_note = f"true live/paper fills: {n_live}."
    goal = _goal()
    need = goal.get("success", {}).get("min_live_trades", 50)
    ok = n_live >= need
    return {"gate": "5. Paper matches backtest", "status": PASS if ok else FAIL,
            "detail": f"{evidence_note} Need >= {need}. "
                      + ("" if ok else "Replay/backtest evidence is excluded from this "
                         "gate. Collect real forward paper fills.")}


def gate6_risk_controls() -> dict:
    rp = _load("risk-policy-report.json")
    dq = _load("data-quality.json")
    live_data = _load("live-data-health.json")
    cb = _load("circuit-breakers.json")
    kill = (ROOT / "safety" / "kill_switch.py").exists()
    states = {
        "risk_policy_valid": "ok" if bool((rp or {}).get("valid")) else ("FAIL" if rp else "MISSING"),
        "data_quality_pass": "ok" if bool((dq or {}).get("pass")) else ("FAIL" if dq else "MISSING"),
        "live_data_health_pass": "ok" if bool((live_data or {}).get("ok")) else ("FAIL" if live_data else "MISSING"),
        "circuit_breakers_present": "ok" if cb is not None else "MISSING",
        "kill_switch_present": "ok" if kill else "MISSING",
    }
    ok = all(v == "ok" for v in states.values())
    return {"gate": "6. Risk controls + kill switch + data health",
            "status": PASS if ok else FAIL,
            "detail": ", ".join(f"{k}={v}" for k, v in states.items())}


def pack_sha() -> str:
    """A short hash of the key validation reports — what a human is approving.
    If any of these change, a prior approval no longer applies."""
    import hashlib
    h = hashlib.sha256()
    for name in ["go-live.json", "walk-forward.json", "stress-test.json",
                 "monte-carlo.json", "validate.json", "data-quality.json",
                 "live-data-health.json", "scorecard-paper.json",
                 "scorecard-live.json", "scorecard-replay.json"]:
        p = REPORTS / name
        h.update((p.read_bytes() if p.exists() else b""))
    return h.hexdigest()[:12]


def gate7_signoff() -> dict:
    p = CONFIG / "go_live_signoff.yaml"
    if not p.exists():
        return {"gate": "7. Human approval", "status": FAIL,
                "detail": "No config/go_live_signoff.yaml — no human has reviewed "
                          "and approved the reporting pack."}
    try:
        import yaml
        s = yaml.safe_load(p.read_text()) or {}
    except Exception:
        s = {}
    approved = s.get("approved") is True
    who = str(s.get("approved_by", "")).strip()
    when = str(s.get("date", "")).strip()
    reviewed_sha = str(s.get("reviewed_pack_sha", "")).strip()
    paper_ok = gate5_paper()["status"] == PASS
    current_sha = pack_sha()
    problems = []
    if not approved:
        problems.append("approved is not true")
    if not who:
        problems.append("approved_by is empty (need a named human)")
    if not when:
        problems.append("date is empty")
    if not paper_ok:
        problems.append("cannot approve a system with no real paper track record "
                        "(gate 5 not passing)")
    if not reviewed_sha:
        problems.append(f"reviewed_pack_sha is empty — set it to the current pack hash "
                        f"({current_sha}) to bind approval to the reports you reviewed")
    elif reviewed_sha != current_sha:
        problems.append(f"reports changed since approval (approved {reviewed_sha}, now "
                        f"{current_sha}) — re-review and re-approve")
    if problems:
        return {"gate": "7. Human approval", "status": FAIL,
                "detail": "; ".join(problems)}
    return {"gate": "7. Human approval", "status": PASS,
            "detail": f"approved by {who} on {when}, bound to reviewed pack {reviewed_sha}, "
                      "with a real paper track record on file."}


def evaluate() -> dict:
    goal = _goal()
    gates = [gate1_walk_forward(goal), gate2_monte_carlo(goal), gate3_stress(),
             gate4_overfitting(goal), gate5_paper(), gate6_risk_controls(),
             gate7_signoff()]
    cleared = all(g["status"] == PASS for g in gates)
    blockers = [g for g in gates if g["status"] in (FAIL, MISSING)]
    needs_human = [g for g in gates if g["status"] == HUMAN]
    verdict = "CLEARED FOR LIVE" if cleared else "BLOCKED"
    return {"asof": datetime.now(timezone.utc).isoformat(),
            "verdict": verdict, "mode": goal.get("mode", "read_only"),
            "gates": gates,
            "blockers": [g["gate"] for g in blockers],
            "needs_human": [g["gate"] for g in needs_human]}


def render(rep: dict) -> str:
    icon = {PASS: "✅", FAIL: "❌", MISSING: "⬜", HUMAN: "🟡"}
    L = ["# GO-LIVE GATE — Section 14 verdict",
         f"_{rep['asof']} · system mode: **{rep['mode']}**_", "",
         f"## VERDICT: {'🟢 ' if rep['verdict']=='CLEARED FOR LIVE' else '🔴 '}**{rep['verdict']}**", ""]
    if rep["verdict"] != "CLEARED FOR LIVE":
        L.append("Real capital must NOT be risked. Observation/paper mode only until "
                 "every gate is green.\n")
    L.append("| # | Gate | Status |")
    L.append("|---|------|--------|")
    for g in rep["gates"]:
        L.append(f"| | {g['gate']} | {icon.get(g['status'],'?')} {g['status']} |")
    L += ["", "## Detail"]
    for g in rep["gates"]:
        L.append(f"- **{g['gate']} — {icon.get(g['status'],'?')} {g['status']}**  \n  {g['detail']}")
    if rep["blockers"]:
        L += ["", "## Hard blockers (must fix)", *[f"- {b}" for b in rep["blockers"]]]
    if rep["needs_human"]:
        L += ["", "## Needs human judgement", *[f"- {h}" for h in rep["needs_human"]]]
    L += ["", "_To grant gate 7: create `config/go_live_signoff.yaml` with "
          "`approved: true`, `approved_by:`, `date:` — only after reviewing the pack._"]
    return "\n".join(L)


def gate_reason_for_live() -> str | None:
    """Enforcement hook for the execution layer. Returns None iff every go-live
    gate is green; otherwise a concise reason a LIVE order must be rejected with.
    Fail-closed: any error evaluating the gates blocks live trading.
    """
    try:
        rep = evaluate()
        if rep["verdict"] == "CLEARED FOR LIVE":
            return None
        bad = rep["blockers"] + rep["needs_human"]
        return ("go-live not cleared (" + ", ".join(bad) + ")") if bad else \
               "go-live not cleared"
    except Exception as e:  # never let an evaluation error open the live path
        return f"go-live verdict unavailable ({type(e).__name__}) — fail-closed"


def main():
    if "--pack-sha" in sys.argv:
        print(pack_sha())
        return
    rep = evaluate()
    (REPORTS / "go-live.json").write_text(json.dumps(rep, indent=2, default=str))
    (REPORTS / "go-live.md").write_text(render(rep))
    if "--json" in sys.argv:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render(rep))
    sys.exit(0 if rep["verdict"] == "CLEARED FOR LIVE" else 2)


if __name__ == "__main__":
    main()
