#!/usr/bin/env python3
"""Single live-readiness status aggregator.

This does not replace lab.go_live. It wraps go-live status with evidence,
incidents, reports, source separation, hashes, and operational health so the
dashboard/stress suite have one honest source of truth.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import ROOT, REPORTS_DIR

REQUIRED_REPORTS = [
    "walk-forward.json", "monte-carlo.json", "stress-test.json", "validate.json",
    "data-quality.json", "live-data-health.json", "circuit-breakers.json", "scorecard-paper.json",
    "go-live.json", "gauntlet.json",
]
MIN_PAPER_OBS_PAPER_READY = 50
MIN_PAPER_OBS_LIVE_REVIEW = 200
MIN_WEEKS_LIVE_REVIEW = 8
MIN_REGIMES_LIVE_REVIEW = 3


def _load_report(name: str, default: Any = None) -> Any:
    try:
        return json.loads((REPORTS_DIR / name).read_text())
    except Exception:
        return default


def _hash_files(names: list[str]) -> str:
    h = hashlib.sha256()
    for name in names:
        p = REPORTS_DIR / name
        h.update(name.encode())
        h.update(p.read_bytes() if p.exists() else b"<missing>")
    return h.hexdigest()[:12]


def code_hash() -> str:
    h = hashlib.sha256()
    for p in sorted(ROOT.rglob("*.py")):
        if ".venv" in p.parts or "__pycache__" in p.parts:
            continue
        h.update(str(p.relative_to(ROOT)).encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:12]


def _paper_summary() -> dict:
    paper = _load_report("scorecard-paper.json", {}) or {}
    live = _load_report("scorecard-live.json", {}) or {}
    replay = _load_report("scorecard-replay.json", {}) or {}
    return {
        "paper_resolved": int(paper.get("resolved", 0) or 0),
        "paper_live_like_resolved": int(paper.get("live_like_resolved_trades", 0) or 0),
        "paper_live_like_signals": int(paper.get("live_like_signal_count", 0) or 0),
        "paper_synthetic_quote_signals": int(paper.get("synthetic_quote_signal_count", 0) or 0),
        "paper_open": int(paper.get("open", 0) or 0),
        "live_resolved": int(live.get("resolved", 0) or 0),
        "live_open": int(live.get("open", 0) or 0),
        "replay_resolved": int(replay.get("resolved", replay.get("n_replay", 0)) or 0),
        "paper_verdict": paper.get("verdict"),
        "live_verdict": live.get("verdict"),
        "replay_verdict": replay.get("verdict"),
    }


def evaluate() -> dict:
    from lab import go_live
    from monitoring import health, live_data_health
    from safety import config_guard, incident_manager, risk_policy

    missing_reports = [name for name in REQUIRED_REPORTS if not (REPORTS_DIR / name).exists()]
    gl = go_live.evaluate()
    open_incidents = incident_manager.list_incidents()
    blocking_incidents = [i for i in open_incidents if i.get("blocks_new_entries")]
    health_report = health.check()
    live_data_report = live_data_health.check()
    rp = risk_policy.report()
    paper = _paper_summary()
    blockers: list[dict[str, Any]] = []

    for name in missing_reports:
        blockers.append({"id": f"missing_report:{name}", "severity": "high",
                         "evidence": name, "required_action": f"Generate reports/{name}"})
    if gl["verdict"] != "CLEARED FOR LIVE":
        blockers.append({"id": "go_live_blocked", "severity": "critical",
                         "evidence": gl.get("blockers", []) + gl.get("needs_human", []),
                         "required_action": "Clear every go-live gate with real evidence."})
    paper_ready_count = paper.get("paper_live_like_resolved", paper["paper_resolved"])
    if paper_ready_count < 50:
        blockers.append({"id": "paper_evidence_thin", "severity": "critical",
                         "evidence": {"live_like_resolved": paper_ready_count, "total_resolved": paper["paper_resolved"]},
                         "required_action": "Collect at least 50 resolved forward paper trades with fresh approved live-like quotes."})
    if blocking_incidents:
        blockers.append({"id": "open_blocking_incidents", "severity": "critical",
                         "evidence": [i["incident_id"] for i in blocking_incidents],
                         "required_action": "Resolve blocking incidents and re-run readiness."})
    if not health_report.get("ok"):
        blockers.append({"id": "health_check_failed", "severity": "high",
                         "evidence": health_report.get("components", {}),
                         "required_action": "Fix failed health components."})
    if not live_data_report.get("ok"):
        blockers.append({"id": "live_data_health_failed", "severity": "high",
                         "evidence": live_data_report.get("hard_failures", []),
                         "required_action": "Start OpenD, refresh moomoo quotes, and re-run live-data health."})

    if blockers:
        verdict = "LIVE_BLOCKED"
    elif paper_ready_count >= 50:
        verdict = "LIVE_LIKE_PAPER_READY"
    else:
        verdict = "PAPER_ONLY"

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "status": verdict,
        "verdict": verdict,
        "mode": config_guard.mode(),
        "live_trading_enabled": False,
        "go_live_status": gl["verdict"],
        "go_live_blockers": gl.get("blockers", []),
        "go_live_needs_human": gl.get("needs_human", []),
        "risk_policy_valid": bool(rp.get("valid")),
        "health": health_report,
        "live_data": live_data_report,
        "missing_reports": missing_reports,
        "paper_evidence": paper,
        "open_incidents": open_incidents,
        "blocking_incidents": blocking_incidents,
        "blockers": blockers,
        "risk_policy_hash": rp.get("version"),
        "report_pack_hash": _hash_files(REQUIRED_REPORTS),
        "code_hash": code_hash(),
        "approval_status": _load_report("go-live.json", {}).get("gates", [])[-1:] if _load_report("go-live.json") else [],
        "safe_next_action": "Run live-like paper mode and collect forward paper evidence.",
        "forbidden_next_action": "Do not enable live trading or bypass go-live gates.",
    }


def _forward_paper_evidence_from_reports() -> dict:
    """Forward paper evidence only. Replay/backtest never counts here."""
    paper = _paper_summary()
    horizon = _load_report("forward-paper-horizon-scorecard-latest.json", {}) or {}
    live_like_resolved = int(paper.get("paper_live_like_resolved", 0) or 0)
    horizon_outcomes = int(horizon.get("outcomes_total", 0) or 0)
    resolved_obs = max(live_like_resolved, horizon_outcomes)
    weeks = int(horizon.get("weeks_covered", 0) or 0)
    regimes = horizon.get("regimes", []) or []
    return {
        "resolved_obs": resolved_obs,
        "weeks": weeks,
        "regimes": len(regimes),
        "decision_useful": bool(horizon.get("decision_useful", False)),
        "total_paper_resolved": int(paper.get("paper_resolved", 0) or 0),
        "synthetic_quote_signals": int(paper.get("paper_synthetic_quote_signals", 0) or 0),
    }


def assess() -> dict:
    """Stricter dashboard/hardening authority view.

    This is a compatibility layer over evaluate() with the anti-hype fields used
    by newer dashboards and hardening-loop tests. It can only report blocked
    unless the existing go-live authority, paper-evidence gate, data health, and
    human approval are all actually satisfied.
    """
    base = evaluate()
    paper = _forward_paper_evidence_from_reports()
    go_live_cleared = base.get("go_live_status") == "CLEARED FOR LIVE"
    critical_incident_open = any(
        i.get("severity") == "critical" and not i.get("resolved")
        for i in base.get("open_incidents", [])
    )
    incident_blocks = bool(base.get("blocking_incidents"))
    kill_switch_halted = False
    try:
        from safety import kill_switch
        kill_switch_halted = bool(kill_switch.status().get("halted"))
    except Exception:
        kill_switch_halted = True

    approval_status = base.get("approval_status") or []
    human_approval = bool(go_live_cleared and approval_status)
    live_data_ok = bool((base.get("live_data") or {}).get("ok"))
    data_quality_ok = "data-quality.json" not in base.get("missing_reports", [])

    if paper["resolved_obs"] == 0 or not data_quality_ok:
        posture = "RESEARCH_ONLY"
    elif paper["resolved_obs"] < MIN_PAPER_OBS_PAPER_READY:
        posture = "PAPER_ONLY"
    elif paper["resolved_obs"] < MIN_PAPER_OBS_LIVE_REVIEW:
        posture = "LIVE_LIKE_PAPER_READY"
    elif paper["weeks"] >= MIN_WEEKS_LIVE_REVIEW and paper["regimes"] >= MIN_REGIMES_LIVE_REVIEW:
        posture = "LIVE_REVIEW_CANDIDATE"
    else:
        posture = "LIVE_LIKE_PAPER_READY"

    blockers: list[str] = []
    if not go_live_cleared:
        blockers.append("go-live authority not cleared")
    if not base.get("risk_policy_valid"):
        blockers.append("risk policy invalid")
    if not data_quality_ok:
        blockers.append("data-quality report missing")
    if not live_data_ok:
        blockers.append("live-data health gate not passing")
    if critical_incident_open:
        blockers.append("a critical incident is open")
    if incident_blocks:
        blockers.append("an open incident blocks new entries")
    if kill_switch_halted:
        blockers.append("kill switch is engaged")
    if paper["resolved_obs"] == 0:
        blockers.append("zero forward PAPER observations (replay/backtest does not count)")
    if not human_approval:
        blockers.append("human go-live approval not in place")

    live_authorized = (
        posture == "LIVE_REVIEW_CANDIDATE"
        and go_live_cleared
        and human_approval
        and base.get("risk_policy_valid")
        and data_quality_ok
        and live_data_ok
        and not critical_incident_open
        and not incident_blocks
        and not kill_switch_halted
        and paper["resolved_obs"] >= MIN_PAPER_OBS_LIVE_REVIEW
    )
    final_verdict = posture if not blockers else (
        "LIVE_BLOCKED" if posture in {"LIVE_LIKE_PAPER_READY", "LIVE_REVIEW_CANDIDATE"} else posture
    )
    return {
        "asof": base.get("asof"),
        "final_verdict": final_verdict,
        "posture": posture,
        "live_authorized": bool(live_authorized),
        "live_blocked": not bool(live_authorized),
        "evidence_source": "live" if paper["resolved_obs"] else (
            "replay" if base.get("paper_evidence", {}).get("replay_resolved", 0) else "none"
        ),
        "paper_evidence": paper,
        "go_live_cleared": go_live_cleared,
        "risk_policy_valid": bool(base.get("risk_policy_valid")),
        "config_guard_paper_safe": base.get("mode") == "paper",
        "data_quality_pass": data_quality_ok,
        "live_data_health_pass": live_data_ok,
        "open_incidents": len(base.get("open_incidents", [])),
        "critical_incident_open": critical_incident_open,
        "kill_switch_halted": kill_switch_halted,
        "human_approval": human_approval,
        "report_pack_sha": base.get("report_pack_hash"),
        "blockers": blockers,
        "next_action": base.get("safe_next_action"),
    }


if __name__ == "__main__":
    print(json.dumps(evaluate(), indent=2, default=str))
