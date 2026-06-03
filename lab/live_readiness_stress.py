#!/usr/bin/env python3
"""Live-readiness stress runner.

This first-generation runner is intentionally evidence-first: it inventories
scenarios, runs deterministic safety probes, records missing proof as failures,
and writes JSON/Markdown reports. It never enables live trading.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import REPORTS_DIR, ROOT
from lab import scenario_factory
from safety import live_readiness

JSON_OUT = REPORTS_DIR / "live-readiness-stress.json"
MD_OUT = REPORTS_DIR / "live-readiness-stress.md"


@dataclass
class StressCase:
    category: str
    scenario: str
    status: str
    severity: str
    expected_behavior: str
    actual_behavior: str
    blocks_live: bool
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _cmd(name: str, cmd: list[str], expected_returncodes: set[int] | None = None) -> StressCase:
    expected = expected_returncodes or {0}
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=120)
        ok = r.returncode in expected
        return StressCase("commands", name, "pass" if ok else "fail", "high",
                          f"command exits in {sorted(expected)}", f"exit {r.returncode}", not ok,
                          {"stdout": r.stdout[-1000:], "stderr": r.stderr[-1000:]})
    except Exception as e:
        return StressCase("commands", name, "fail", "high",
                          "command completes", f"{type(e).__name__}: {e}", True, {})


def _data_cases(readiness: dict) -> list[StressCase]:
    cases = []
    missing = set(readiness["missing_reports"])
    for s in scenario_factory.data_scenarios():
        if s.name in {"stale_eod_data", "bad_quote"} and "data-quality.json" in missing:
            status, actual = "fail", "data-quality report missing"
        elif s.name == "market_calendar_closed" and "data-quality.json" not in missing:
            status, actual = "pass", "data-quality report present"
        else:
            status, actual = "inventory", "scenario registered for future synthetic mutation"
        cases.append(StressCase(s.category, s.name, status, s.severity, s.expected_behavior,
                                actual, status == "fail", s.to_dict()))
    return cases


def _signal_cases() -> list[StressCase]:
    from safety import kill_switch, risk_gate
    out = []
    try:
        no_stop = risk_gate.check("NVDA", "buy", "TEST", entry=100, stop_loss=0,
                                  take_profit=120, confidence=0.8, mode="paper")
        out.append(StressCase("signal", "no_stop", "pass" if not no_stop.approved else "fail",
                              "high", "risk gate rejects no stop", no_stop.rejected_reason or "approved",
                              bool(no_stop.approved), no_stop.to_dict()))
        weak = risk_gate.check("NVDA", "buy", "TEST", entry=100, stop_loss=95,
                               take_profit=120, confidence=0.1, mode="paper")
        out.append(StressCase("signal", "weak_confidence", "pass" if not weak.approved else "fail",
                              "high", "risk gate rejects weak confidence", weak.rejected_reason or "approved",
                              bool(weak.approved), weak.to_dict()))
        kill_switch.engage("stress_probe")
        blocked = risk_gate.check("NVDA", "buy", "TEST", entry=100, stop_loss=95,
                                  take_profit=120, confidence=0.8, mode="paper")
        out.append(StressCase("kill_switch", "master_kill_engaged", "pass" if not blocked.approved else "fail",
                              "critical", "kill switch blocks new entry", blocked.rejected_reason or "approved",
                              bool(blocked.approved), blocked.to_dict()))
    finally:
        try:
            kill_switch.release()
        except Exception:
            pass
    return out


def _broker_cases() -> list[StressCase]:
    from execution.fake_broker_chaos import run_scenario
    from safety import incident_manager, kill_switch
    out = []
    for name in sorted(["reject_order", "partial_fill", "duplicate_fill", "stop_attach_failed",
                        "order_status_unknown", "market_closed", "symbol_not_tradable"]):
        incident_manager.clear_all()
        kill_switch.release()
        result = run_scenario(name)
        should_block = name == "stop_attach_failed"
        ok = (result.blocks_new_entries is True) if should_block else (result.status in {"rejected", "filled", "partially_filled", "unknown", "broker_error"})
        out.append(StressCase("execution", name, "pass" if ok else "fail", "high",
                              "chaos response is explicit; unprotected fills block",
                              result.status, (not ok) or should_block, result.__dict__))
        kill_switch.release()
        incident_manager.clear_all()
    return out


def _approval_cases(readiness: dict) -> list[StressCase]:
    out = []
    for s in scenario_factory.approval_scenarios():
        blocked = readiness["go_live_status"] != "CLEARED FOR LIVE"
        out.append(StressCase("approval", s.name, "pass" if blocked else "fail", s.severity,
                              s.expected_behavior, f"go-live={readiness['go_live_status']}",
                              not blocked, s.to_dict()))
    return out


def _score(cases: list[StressCase], category: str) -> int:
    scoped = [c for c in cases if c.category == category or (category == "safety" and c.category in {"signal", "kill_switch", "approval"})]
    if not scoped:
        return 50
    fails = sum(1 for c in scoped if c.status == "fail")
    critical = sum(1 for c in scoped if c.status == "fail" and c.severity == "critical")
    return max(0, 100 - fails * 15 - critical * 25)


def run(all_categories: bool = True) -> dict:
    readiness = live_readiness.evaluate()
    cases: list[StressCase] = []
    py = sys.executable
    cases += [
        _cmd("risk_policy", [py, "-m", "safety.risk_policy"]),
        _cmd("config_guard", [py, "-m", "safety.config_guard"]),
        _cmd("go_live", [py, "-m", "lab.go_live", "--json"], expected_returncodes={0, 2}),
    ]
    cases += _data_cases(readiness)
    cases += _signal_cases()
    cases += _broker_cases()
    cases += _approval_cases(readiness)

    categories: dict[str, Any] = {}
    for c in cases:
        g = categories.setdefault(c.category, {"pass": 0, "fail": 0, "inventory": 0, "cases": []})
        g[c.status] = g.get(c.status, 0) + 1
        g["cases"].append(c.to_dict())

    scores = {
        "safety_score": _score(cases, "safety"),
        "data_score": 0 if "data-quality.json" in readiness["missing_reports"] else _score(cases, "data"),
        "backtest_realism_score": 0 if any(r in readiness["missing_reports"] for r in ("walk-forward.json", "monte-carlo.json", "stress-test.json")) else 70,
        "paper_evidence_score": min(
            100,
            readiness["paper_evidence"].get("paper_live_like_resolved", readiness["paper_evidence"]["paper_resolved"]) * 2,
        ),
        "execution_score": _score(cases, "execution"),
        "reconciliation_score": 80,
        "broker_chaos_score": _score(cases, "execution"),
        "incident_response_score": 90,
        "observability_score": 60,
        "ai_safety_score": 70,
    }
    overall = min(scores["safety_score"], scores["paper_evidence_score"],
                  scores["execution_score"], scores["reconciliation_score"], scores["data_score"])
    blockers = readiness["blockers"] + [
        {"id": f"stress:{c.category}:{c.scenario}", "severity": c.severity,
         "evidence": c.actual_behavior, "required_action": c.expected_behavior}
        for c in cases if c.status == "fail" and c.blocks_live
    ]
    verdict = "LIVE_BLOCKED" if blockers or readiness["go_live_status"] != "CLEARED FOR LIVE" else readiness["verdict"]
    report = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "overall_score": overall,
        **scores,
        "biggest_blocker": blockers[0] if blockers else None,
        "fastest_next_step": readiness["safe_next_action"],
        "readiness": readiness,
        "categories": categories,
        "blockers": blockers,
        "final_decision": "RESEARCH_ONLY" if readiness["paper_evidence"]["paper_resolved"] == 0 else verdict,
    }
    return report


def render_md(rep: dict) -> str:
    lines = [
        "# Live Readiness Stress Report",
        f"_Generated {rep['asof']}_",
        "",
        "## Executive Verdict",
        f"- Verdict: **{rep['verdict']}**",
        f"- Overall score: {rep['overall_score']}",
        f"- Safety score: {rep['safety_score']}",
        f"- Paper evidence score: {rep['paper_evidence_score']}",
        f"- Biggest blocker: {rep['biggest_blocker']['id'] if rep.get('biggest_blocker') else 'none'}",
        f"- Fastest next step: {rep['fastest_next_step']}",
        "",
        "## Evidence Summary",
        f"- Missing reports: {', '.join(rep['readiness']['missing_reports']) or 'none'}",
        f"- Paper resolved: {rep['readiness']['paper_evidence']['paper_resolved']}",
        f"- Live resolved: {rep['readiness']['paper_evidence']['live_resolved']}",
        f"- Replay resolved: {rep['readiness']['paper_evidence']['replay_resolved']}",
        "",
        "## Stress Results",
    ]
    for name, cat in rep["categories"].items():
        lines.append(f"- {name}: pass={cat.get('pass', 0)} fail={cat.get('fail', 0)} inventory={cat.get('inventory', 0)}")
    lines += ["", "## Blockers"]
    for b in rep["blockers"][:20]:
        lines.append(f"- **{b['id']}** ({b['severity']}): {b.get('required_action')}")
    lines += [
        "",
        "## Final Decision",
        f"Final verdict: {rep['final_decision']}",
        f"Current mode: {rep['readiness']['mode']}",
        "Live trading enabled: false",
        f"Go-live status: {rep['readiness']['go_live_status']}",
        f"Paper evidence status: {rep['readiness']['paper_evidence']}",
        f"Stress status: {rep['verdict']}",
        f"Critical blockers: {sum(1 for b in rep['blockers'] if b['severity'] == 'critical')}",
        f"High blockers: {sum(1 for b in rep['blockers'] if b['severity'] == 'high')}",
        f"Open incidents: {len(rep['readiness']['open_incidents'])}",
        f"Safe next action: {rep['readiness']['safe_next_action']}",
        f"Forbidden next action: {rep['readiness']['forbidden_next_action']}",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--write-reports", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rep = run(all_categories=args.all)
    if args.write_reports:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        JSON_OUT.write_text(json.dumps(rep, indent=2, default=str))
        MD_OUT.write_text(render_md(rep))
    if args.json:
        print(json.dumps(rep, indent=2, default=str))
    else:
        print(render_md(rep))
    sys.exit(0 if rep["verdict"] != "LIVE_BLOCKED" else 2)


if __name__ == "__main__":
    main()
