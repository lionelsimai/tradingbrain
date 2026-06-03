#!/usr/bin/env python3
"""Bounded live-readiness hardening loop.

The loop strengthens by proof, not by optimism. Each iteration runs the stress
suite, the forbidden-live weakening scan, and the live-readiness authority. It
aborts if safety weakens or live becomes unblocked. It does not auto-edit risk
thresholds, disable tests, mark tests xfail, or enable live trading.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from paths import REPORTS_DIR, ROOT
from lab import live_readiness_stress
from loops import improvement_backlog

OUT = REPORTS_DIR / "hardening-live-readiness.json"
OUT_CANON = REPORTS_DIR / "hardening-report.json"
OUT_MD = REPORTS_DIR / "hardening-report.md"

FORBIDDEN_PATCHES = (
    "live_trading_enabled: true",
    "require_human_approval_for_live: false",
    "require_stop_loss: false",
    "allow_market_orders: true",
    "replay_not_allowed_for_live_gate: false",
    "paper_not_allowed_for_live_gate: false",
    "remove kill_switch",
    "remove risk_gate.check",
    "remove config_guard.safe_to_trade",
    "remove protective order requirement",
    "remove reconciliation blocking",
    "count replay as paper evidence",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _forbidden_scan_passes() -> bool:
    script = ROOT / "scripts" / "ci_forbidden_live_weakening.sh"
    if not script.exists():
        return False
    try:
        r = subprocess.run(["bash", str(script)], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
        return r.returncode == 0
    except Exception:
        return False


def _rank_failures(stress: dict) -> list[dict]:
    failures: list[dict] = []
    for category_name, category in (stress.get("categories") or {}).items():
        cases = category.get("cases") or category.get("results") or []
        for case in cases:
            failed = case.get("status") == "fail" or case.get("pass") is False
            if not failed:
                continue
            severity = case.get("severity", "medium")
            priority = "P0" if severity == "critical" else ("P1" if severity == "high" else "P2")
            failures.append({
                "priority": priority,
                "category": category_name,
                "scenario": case.get("scenario") or case.get("name"),
                "detail": case.get("actual_behavior") or case.get("detail"),
                "severity": severity,
            })
    order = {"P0": 0, "P1": 1, "P2": 2}
    return sorted(failures, key=lambda row: order.get(row["priority"], 9))


def _run_iteration() -> dict:
    from safety import live_readiness

    stress = live_readiness_stress.run(all_categories=True)
    authority = live_readiness.assess()
    failures = _rank_failures(stress)
    p0 = [f for f in failures if f["priority"] == "P0"]
    p1 = [f for f in failures if f["priority"] == "P1"]
    return {
        "asof": _now(),
        "stress_verdict": stress.get("verdict"),
        "overall_score": stress.get("overall_score"),
        "invariant_forbidden_scan_pass": _forbidden_scan_passes(),
        "invariant_live_blocked": bool(authority["live_blocked"]),
        "p0_failures": p0,
        "p1_failures": p1,
        "remaining_failures": failures,
        "primary_gap": p0[0] if p0 else (p1[0] if p1 else None),
        "authority_blockers": authority["blockers"],
    }


def harden(max_iters: int = 10) -> dict:
    trace = []
    aborted = None
    for _ in range(max(1, int(max_iters))):
        item = _run_iteration()
        trace.append(item)
        if not item["invariant_forbidden_scan_pass"]:
            aborted = "ABORT: forbidden-live weakening scan failed."
            break
        if not item["invariant_live_blocked"]:
            aborted = "ABORT: live became unblocked during hardening."
            break
        if not item["p0_failures"] and not item["p1_failures"]:
            break

    last = trace[-1]
    converged = aborted is None and not last["p0_failures"] and not last["p1_failures"]
    report = {
        "asof": _now(),
        "iterations": len(trace),
        "converged": converged,
        "aborted": aborted,
        "final_stress_verdict": last["stress_verdict"],
        "final_overall_score": last["overall_score"],
        "remaining_p0": last["p0_failures"],
        "remaining_p1": last["p1_failures"],
        "primary_gap": last["primary_gap"],
        "forbidden_patches_guarded": list(FORBIDDEN_PATCHES),
        "authority_blockers": last["authority_blockers"],
        "trace": trace,
        "live_enabled": False,
        "headline": (
            "No P0/P1 stress failures remain; next strength comes from forward paper evidence."
            if converged else (aborted or "Open P0/P1 stress failures remain.")
        ),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    OUT_CANON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(_render_md(report))
    return report


def run(max_iters: int = 10) -> dict:
    """Compatibility API for the improvement-backlog loop.

    Older tests and tools use this function to verify the targeted
    Build->Review->Test->Fix backlog is embedded in the hardening report. Keep
    that surface stable while `harden()` carries the newer invariant checks.
    """
    history = []
    backlog = {"items": []}
    for i in range(1, max(1, int(max_iters)) + 1):
        stress = live_readiness_stress.run(all_categories=True)
        blockers = stress.get("blockers", [])
        backlog = improvement_backlog.build(stress)
        p0p1 = [b for b in blockers if b.get("severity") in {"critical", "high"}]
        history.append({
            "iteration": i,
            "verdict": stress.get("verdict"),
            "p0_p1_blockers": len(p0p1),
            "top_blocker": p0p1[0] if p0p1 else None,
            "top_backlog_item": backlog.get("top_item"),
            "automatic_patch_candidates": backlog.get("automatic_patch_candidates", 0),
        })
        if not p0p1:
            break
        break
    report = {
        "asof": _now(),
        "max_iters": max_iters,
        "iterations": history,
        "forbidden_actions": list(FORBIDDEN_PATCHES),
        "live_enabled": False,
        "next_fix": history[-1].get("top_blocker") if history else None,
        "improvement_backlog": backlog,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    if history:
        improvement_backlog.write(backlog)
    return report


def _render_md(rep: dict) -> str:
    lines = [
        "# Self-Hardening Report",
        f"_As of {rep['asof']}_",
        "",
        f"- Iterations: {rep['iterations']}",
        f"- Converged: {rep['converged']}",
        f"- Aborted: {rep['aborted']}",
        f"- Final stress verdict: {rep['final_stress_verdict']}",
        f"- Remaining P0: {len(rep['remaining_p0'])}",
        f"- Remaining P1: {len(rep['remaining_p1'])}",
        "",
        rep["headline"],
        "",
        "## Authority Blockers",
    ]
    lines.extend(f"- {b}" for b in rep.get("authority_blockers", []))
    lines += ["", "## Forbidden Patches Guarded"]
    lines.extend(f"- `{p}`" for p in rep.get("forbidden_patches_guarded", []))
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-iters", type=int, default=10)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = harden(args.max_iters)
    print(json.dumps(rep, indent=2, default=str) if args.json else _render_md(rep))
    return 0 if rep["aborted"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
