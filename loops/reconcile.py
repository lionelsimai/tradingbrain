#!/usr/bin/env python3
"""Close the recursive-learning loop (DOCTRINE v3 §9-10 / v4 across-task).

Reads the LIVE forward-test scorecard and the BACKTEST research report, detects
where live edge diverges from the validated claim, and AUTONOMOUSLY:
  - updates strategy_library status (Validated -> Probation/Broken on live drift)
  - distills durable lessons + failure-log entries (Meta-Learner)
  - writes reports/reconciliation.json + a human-readable summary

This is what makes the brain self-correct without a human: a strategy that
passed the 30y backtest but bleeds money live is auto-demoted, and the live
gate (calibration.live_gated) already suppresses it at decision time.
"""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SCORECARD = ROOT / "reports" / "live-scorecard.json"
RESEARCH = ROOT / "reports" / "research-report.json"
OUT = ROOT / "reports" / "reconciliation.json"
sys.path.insert(0, str(ROOT))
from scripts.collective import memory

# Drift thresholds
DRIFT_PROBATION = -0.15   # live exp this much below backtest -> Probation
LIVE_BROKEN = 0.0         # live exp below this (negative) -> Broken
MIN_N = 25                # need this many resolved trades to act

def main():
    if not SCORECARD.exists():
        print("No live scorecard yet."); return
    sc = json.loads(SCORECARD.read_text())
    research = json.loads(RESEARCH.read_text()).get("strategies", {}) if RESEARCH.exists() else {}
    cycle_id = "reconcile_" + datetime.now(timezone.utc).strftime("%Y%m%d")

    per = sc.get("by_setup", {})
    actions = []
    for setup, s in per.items():
        n = s.get("n", 0)
        live = s.get("expectancy_R")
        if n < MIN_N or live is None:
            continue
        # Primary baseline = the unified calibration expectancy the scorecard
        # already carries (same detector + plan + exit). Fall back to research.
        bt = s.get("backtest_expectancy_R")
        if bt is None:
            bt = (research.get(setup, {}) or {}).get("full", {}).get("expectancy_R")
        if bt is None:
            bt = (research.get(setup, {}) or {}).get("oos_exp")
        drift = (live - bt) if bt is not None else None
        bt_str = f"{bt:+.3f}R" if bt is not None else "n/a"

        if live < LIVE_BROKEN:
            status, verdict = "Broken", "Reject"
            lesson = (f"{setup}: live edge is NEGATIVE ({live:+.3f}R over {n} trades) despite "
                      f"backtest {bt_str}. Auto-demoted to Broken; live gate suppresses it. "
                      f"Backtest overstated this setup in the current regime.")
            memory.log_failure(cycle_id, setup, "live edge flipped negative vs backtest",
                               context=f"live {live:+.3f}R n={n}, backtest {bt_str}", source="live")
        elif drift is not None and drift <= DRIFT_PROBATION:
            status, verdict = "Probation", "Iterate"
            lesson = (f"{setup}: live edge {live:+.3f}R is decaying vs backtest {bt_str} "
                      f"(drift {drift:+.3f}). On probation; size capped until it recovers.")
        else:
            status, verdict = "Validated", "Deploy"
            lesson = (f"{setup}: live edge {live:+.3f}R confirms backtest "
                      f"({bt_str}) over {n} trades. Validated.")

        lid = memory.add_lesson(cycle_id, lesson, category="live-reconciliation",
                                evidence=f"scorecard n={n}", confidence=min(0.9, 0.5 + n/2000))
        memory.upsert_strategy(setup, status, verdict, oos_expectancy_R=live)
        actions.append({"setup": setup, "n": n, "live_exp_R": live, "backtest_exp_R": bt,
                        "drift": round(drift, 3) if drift is not None else None,
                        "status": status, "verdict": verdict, "lesson_id": lid})

    OUT.write_text(json.dumps({
        "asof": datetime.now(timezone.utc).isoformat(),
        "min_n": MIN_N, "actions": actions,
        "summary": {
            "validated": [a["setup"] for a in actions if a["status"] == "Validated"],
            "probation": [a["setup"] for a in actions if a["status"] == "Probation"],
            "broken": [a["setup"] for a in actions if a["status"] == "Broken"],
        },
    }, indent=2, default=str))

    print(f"Reconciliation — {len(actions)} strategies reviewed:")
    for a in actions:
        tag = {"Validated": "✅", "Probation": "⚠️", "Broken": "⛔"}[a["status"]]
        d = f" drift {a['drift']:+.3f}" if a["drift"] is not None else ""
        bt = a["backtest_exp_R"]
        bt_s = f"{bt:+.3f}R" if bt is not None else "n/a"
        print(f"  {tag} {a['setup']:16} live {a['live_exp_R']:+.3f}R vs bt {bt_s}{d} -> {a['status']}")
    print(f"  Wrote {OUT}")

if __name__ == "__main__":
    main()
