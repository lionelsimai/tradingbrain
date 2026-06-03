#!/usr/bin/env python3
"""Read-only live feature preflight.

This command enables an operator to inspect every live-facing feature without
enabling real-money execution. It writes an evidence report that separates
read-only/paper capabilities from prohibited live order submission.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import REPORTS_DIR, ROOT
from safety import config_guard, incident_manager, live_readiness, risk_policy
from lab import go_live
from monitoring import live_data_health, live_readiness_dashboard

OUT_JSON = REPORTS_DIR / "live-feature-preflight.json"
OUT_MD = REPORTS_DIR / "live-feature-preflight.md"


def _env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split("#", 1)[0].strip().strip("'\"")
    return values


def _merged_env() -> dict[str, str]:
    merged = dict(_env_file_values())
    merged.update({k: v for k, v in os.environ.items() if isinstance(v, str)})
    return merged


def _feature(feature_id: str, status: str, detail: str, *, blocks_live: bool) -> dict[str, Any]:
    return {
        "id": feature_id,
        "status": status,
        "detail": detail,
        "blocks_live": bool(blocks_live),
    }


def run(*, require_realtime_data: bool = True, write_reports: bool = False) -> dict[str, Any]:
    env = _merged_env()
    policy_report = risk_policy.report()
    policy = risk_policy.load()
    policy_env = policy["environment"]
    live_prereqs = risk_policy.live_prerequisites(env)
    paper_safe, paper_reasons = config_guard.safe_to_trade("paper")
    live_safe, live_reasons = config_guard.safe_to_trade("live")
    go_live_report = go_live.evaluate()
    readiness = live_readiness.assess()
    data_health = live_data_health.check(require_realtime=require_realtime_data)
    dashboard = live_readiness_dashboard.write()
    open_incidents = incident_manager.list_incidents()
    blocking_incidents = [i for i in open_incidents if i.get("blocks_new_entries")]

    broker_keys_present = bool(env.get("APCA_API_KEY_ID") and env.get("APCA_API_SECRET_KEY"))
    live_flags_requested = env.get("TB_MODE", "paper").lower() == "live" or env.get("TB_ALLOW_LIVE") == "1"

    features = [
        _feature(
            "canonical_risk_policy",
            "READY" if policy_report.get("valid") else "BLOCKED",
            "risk_policy.yaml is valid" if policy_report.get("valid") else str(policy_report.get("error") or policy_report.get("conflicts")),
            blocks_live=not bool(policy_report.get("valid")),
        ),
        _feature(
            "paper_execution_path",
            "READY" if paper_safe else "BLOCKED",
            "paper mode safe_to_trade passed" if paper_safe else "; ".join(paper_reasons),
            blocks_live=False,
        ),
        _feature(
            "broker_credentials",
            "READY" if broker_keys_present else "BLOCKED",
            "Alpaca credentials are present and masked" if broker_keys_present else "Alpaca credentials are absent",
            blocks_live=not broker_keys_present,
        ),
        _feature(
            "live_data_health",
            "READY" if data_health.get("ok") else "BLOCKED",
            "live data health passed" if data_health.get("ok") else "; ".join(data_health.get("hard_failures", [])),
            blocks_live=not bool(data_health.get("ok")),
        ),
        _feature(
            "go_live_authority",
            "READY" if go_live_report.get("verdict") == "CLEARED FOR LIVE" else "BLOCKED",
            go_live_report.get("verdict", "BLOCKED"),
            blocks_live=go_live_report.get("verdict") != "CLEARED FOR LIVE",
        ),
        _feature(
            "forward_paper_evidence",
            "READY" if readiness["paper_evidence"]["resolved_obs"] >= live_readiness.MIN_PAPER_OBS_LIVE_REVIEW else "BLOCKED",
            f"{readiness['paper_evidence']['resolved_obs']} resolved forward paper observations",
            blocks_live=readiness["paper_evidence"]["resolved_obs"] < live_readiness.MIN_PAPER_OBS_LIVE_REVIEW,
        ),
        _feature(
            "incident_gate",
            "READY" if not blocking_incidents else "BLOCKED",
            "no blocking incidents open" if not blocking_incidents else f"{len(blocking_incidents)} blocking incidents open",
            blocks_live=bool(blocking_incidents),
        ),
        _feature(
            "dashboard_truthfulness",
            "READY" if dashboard.get("live_blocked") and not dashboard.get("live_authorized") else "BLOCKED",
            "dashboard shows blocked while authority is blocked",
            blocks_live=not (dashboard.get("live_blocked") and not dashboard.get("live_authorized")),
        ),
    ]

    blockers = [f for f in features if f["blocks_live"]]
    if live_flags_requested:
        blockers.append(
            _feature(
                "unsafe_live_flags_requested",
                "BLOCKED",
                "TB_MODE=live or TB_ALLOW_LIVE=1 is set, but live execution remains locked",
                blocks_live=True,
            )
        )

    all_live_gates_clear = (
        policy_env.get("live_trading_enabled") is True
        and not live_prereqs
        and live_safe
        and go_live_report.get("verdict") == "CLEARED FOR LIVE"
        and readiness.get("live_authorized") is True
        and not blockers
    )

    report = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "verdict": "LIVE_REVIEW_READY_EXECUTION_LOCKED" if all_live_gates_clear else "LIVE_EXECUTION_LOCKED",
        "execution_enabled": False,
        "live_execution_authorized": False,
        "all_live_gates_clear": bool(all_live_gates_clear),
        "paper_trading_enabled": paper_safe,
        "read_only_live_features_enabled": True,
        "mode": env.get("TB_MODE", "paper"),
        "allow_live_flag": env.get("TB_ALLOW_LIVE", "0"),
        "human_approved_flag": env.get("TB_HUMAN_APPROVED", "0"),
        "broker_key_id_masked": config_guard.mask(env.get("APCA_API_KEY_ID")),
        "risk_policy_hash": policy_report.get("version"),
        "go_live_status": go_live_report.get("verdict"),
        "readiness_verdict": readiness.get("final_verdict"),
        "features": features,
        "blockers": blockers,
        "live_prerequisites": live_prereqs,
        "live_safe_to_trade_reasons": live_reasons,
        "data_health": data_health,
        "dashboard_report": str(live_readiness_dashboard.OUT),
        "safe_next_action": "Run paper/live-like preflight, collect forward paper evidence, and clear reports before any live review.",
        "forbidden_next_action": "Do not enable live trading, submit real-money orders, or bypass go-live gates.",
    }
    if write_reports:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
        OUT_MD.write_text(render_md(report))
    return report


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Live Feature Preflight",
        "",
        f"- Verdict: {report['verdict']}",
        f"- Execution enabled: {report['execution_enabled']}",
        f"- Paper trading enabled: {report['paper_trading_enabled']}",
        f"- Go-live status: {report['go_live_status']}",
        f"- Readiness verdict: {report['readiness_verdict']}",
        "",
        "## Features",
    ]
    for feature in report["features"]:
        lines.append(
            f"- {feature['id']}: {feature['status']} - {feature['detail']}"
        )
    if report["blockers"]:
        lines.extend(["", "## Live Blockers"])
        for blocker in report["blockers"]:
            lines.append(f"- {blocker['id']}: {blocker['detail']}")
    lines.extend([
        "",
        f"Safe next action: {report['safe_next_action']}",
        f"Forbidden next action: {report['forbidden_next_action']}",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-reports", action="store_true")
    ap.add_argument("--no-require-realtime", action="store_true")
    args = ap.parse_args(argv)
    report = run(
        require_realtime_data=not args.no_require_realtime,
        write_reports=args.write_reports,
    )
    print(json.dumps(report, indent=2, default=str))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
