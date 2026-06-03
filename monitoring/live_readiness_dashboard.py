#!/usr/bin/env python3
"""Live-readiness dashboard JSON: one read-only screen of truth.

Truthfulness guarantees:
  - never shows live-ready while blocked,
  - never counts replay/backtest rows as forward-paper evidence,
  - never presents missing reports as a pass,
  - preserves the legacy dashboard fields existing app code expects.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from paths import REPORTS_DIR
from safety import live_readiness

OUT = REPORTS_DIR / "live-readiness-dashboard.json"


def _json(name: str, default=None):
    try:
        return json.loads((REPORTS_DIR / name).read_text())
    except Exception:
        return default if default is not None else {}


def build() -> dict:
    legacy = live_readiness.evaluate()
    authority = live_readiness.assess()
    stress = _json("live-readiness-stress.json", {})

    missing_warnings = [
        f"missing report: {name}"
        for name in live_readiness.REQUIRED_REPORTS
        if not (REPORTS_DIR / name).exists()
    ]
    paper = authority["paper_evidence"]
    dash = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "status": legacy["status"],
        "verdict": authority["final_verdict"],
        "posture": authority["posture"],
        "mode": legacy["mode"],
        "current_mode": legacy["mode"],
        "live_authorized": authority["live_authorized"],
        "live_blocked": authority["live_blocked"],
        "go_live_status": legacy["go_live_status"],
        "go_live_cleared": authority["go_live_cleared"],
        "kill_switch_halted": authority["kill_switch_halted"],
        "blockers": legacy["blockers"],
        "authority_blockers": authority["blockers"],
        "warnings": legacy["go_live_needs_human"] + missing_warnings,
        "open_incidents": legacy["open_incidents"],
        "critical_incident_open": authority["critical_incident_open"],
        "last_stress_run": stress.get("asof"),
        "stress_status": stress.get("verdict"),
        "stress": {
            "verdict": stress.get("verdict", "not-run"),
            "overall_score": stress.get("overall_score"),
            "asof": stress.get("asof"),
        },
        "live_data_health": legacy["live_data"],
        "data_quality_pass": authority["data_quality_pass"],
        "paper_evidence": {
            "resolved_forward_paper_obs": paper["resolved_obs"],
            "weeks": paper["weeks"],
            "regimes": paper["regimes"],
            "evidence_source": authority["evidence_source"],
        },
        "paper_evidence_summary": legacy["paper_evidence"],
        "risk_policy_hash": legacy["risk_policy_hash"],
        "report_pack_hash": legacy["report_pack_hash"],
        "report_pack_sha": authority["report_pack_sha"],
        "approval_status": legacy["approval_status"],
        "human_approval": authority["human_approval"],
        "research_only_warning": legacy["go_live_status"] != "CLEARED FOR LIVE",
        "next_action": authority["next_action"],
        "truthfulness": {
            "advertises_live_ready": bool(authority["live_authorized"]),
            "conviction_cap_active": _json("recommendations.json", {}).get("conviction_cap_active", True),
            "paper_is_forward_only": paper["resolved_obs"] == 0 or authority["evidence_source"] != "replay",
            "missing_reports_are_warnings": bool(missing_warnings) or not legacy["missing_reports"],
        },
        "disclaimer": (
            "Research/paper only unless the live-readiness authority authorizes live. "
            "Replay and backtest evidence are never shown as forward-paper proof."
        ),
    }
    assert not (dash["live_blocked"] and dash["live_authorized"]), (
        "dashboard cannot be blocked and live-authorized at the same time"
    )
    assert dash["truthfulness"]["advertises_live_ready"] == dash["live_authorized"]
    assert dash["live_authorized"] or dash["verdict"] != "LIVE_REVIEW_CANDIDATE"
    return dash


def write() -> dict:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = build()
    OUT.write_text(json.dumps(out, indent=2, default=str))
    return out


def main() -> int:
    print(json.dumps(write(), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
