#!/usr/bin/env python3
"""Build a prioritized hardening backlog from readiness evidence.

This is the self-improvement bridge between "stress found blockers" and "what
should the system do next?" It stays conservative: it may recommend safe tests,
reports, and operational commands, but it never enables live trading or weakens
risk policy.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import REPORTS_DIR

JSON_OUT = REPORTS_DIR / "improvement-backlog.json"
MD_OUT = REPORTS_DIR / "improvement-backlog.md"

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
FORBIDDEN_ACTIONS = [
    "enable live trading",
    "weaken risk thresholds",
    "count replay/backtest as paper evidence",
    "bypass human approval",
    "ignore failed data health",
]
PROCESS_PRINCIPLE = (
    "Build -> Review -> Test -> Fix specific failures. Use targeted refinement "
    "prompts and test-driven gates; avoid open-ended self-refinement."
)


@dataclass
class BacklogItem:
    item_id: str
    severity: str
    priority: int
    source_blocker_id: str
    patch_class: str
    automatic_patch_allowed: bool
    title: str
    rationale: str
    required_evidence: list[str]
    safe_next_action: str
    validation_command: str
    forbidden_actions: list[str]
    status: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm_severity(value: Any) -> str:
    sev = str(value or "medium").lower()
    return sev if sev in SEVERITY_RANK else "medium"


def _title(blocker_id: str) -> str:
    mapping = {
        "go_live_blocked": "Clear go-live evidence gates without bypassing safety",
        "paper_evidence_thin": "Collect real forward paper evidence",
        "live_data_health_failed": "Restore moomoo real-time market-data health",
        "health_check_failed": "Fix failed operational health components",
        "open_blocking_incidents": "Resolve blocking incidents",
    }
    if blocker_id in mapping:
        return mapping[blocker_id]
    if blocker_id.startswith("missing_report:"):
        return f"Generate required report: {blocker_id.split(':', 1)[1]}"
    if blocker_id.startswith("stress:"):
        return f"Fix stress failure: {blocker_id}"
    return blocker_id.replace("_", " ").replace(":", " - ").title()


def _classify(blocker: dict[str, Any]) -> tuple[str, bool, str, str, list[str]]:
    blocker_id = str(blocker.get("id", "unknown"))
    evidence = blocker.get("evidence")
    if blocker_id == "paper_evidence_thin":
        return (
            "evidence_collection",
            False,
            "Run paper mode with live-like quotes until at least 50 resolved forward paper observations exist.",
            "python3 -m loops.forward_paper_runner --once --require-live-data",
            [
                "reports/scorecard-paper.json with live_like_resolved_trades >= 50",
                "forward-paper JSONL files with paper-only fills and fresh moomoo decision quotes",
            ],
        )
    if blocker_id == "live_data_health_failed":
        return (
            "operational_dependency",
            False,
            "Start moomoo OpenD, refresh quotes, and verify reports/live-data-health.json is PASS.",
            "python3 -m monitoring.live_data_health --write-report",
            ["reports/live-data-health.json ok=true", "reports/moomoo-live-quotes.json from moomoo"],
        )
    if blocker_id == "go_live_blocked":
        return (
            "evidence_gate",
            False,
            "Resolve each named go-live gate with real artifacts; do not edit signoff until evidence exists.",
            "python3 -m lab.go_live --json",
            ["reports/go-live.json shows all gates PASS", "human signoff bound to current pack hash"],
        )
    if blocker_id == "health_check_failed":
        return (
            "observability_or_dependency",
            False,
            "Inspect failed health components and fix the underlying report, data, or service.",
            "python3 -m safety.operator health",
            ["monitoring health components all ok=true", f"evidence={evidence}"],
        )
    if blocker_id.startswith("missing_report:"):
        report = blocker_id.split(":", 1)[1]
        return (
            "report_generation",
            True,
            f"Generate reports/{report} using the canonical module, then rerun readiness.",
            "python3 -m scripts.validate_all",
            [f"reports/{report} exists", "python3 -m lab.go_live --json still blocks honestly unless all gates pass"],
        )
    if blocker_id.startswith("stress:commands:"):
        return (
            "bug_fix",
            True,
            "Fix the failing command or its invocation, then add a regression test for the failure mode.",
            "python3 -m lab.live_readiness_stress --all --write-reports",
            ["stress command status pass", "targeted regression test passes"],
        )
    if blocker_id.startswith("stress:"):
        return (
            "test_or_safety_fix",
            True,
            "Fix the failing safety behavior and add a deterministic stress regression test.",
            "python3 -m pytest -q tests/test_live_readiness_stress.py",
            ["stress case passes", "no forbidden live weakening"],
        )
    return (
        "manual_review",
        False,
        str(blocker.get("required_action") or "Review blocker and define evidence."),
        "python3 -m lab.live_readiness_stress --all --write-reports",
        ["blocker removed from reports/live-readiness-stress.json"],
    )


def _dedupe(blockers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for blocker in blockers:
        blocker_id = str(blocker.get("id", "unknown"))
        if blocker_id in seen:
            continue
        seen.add(blocker_id)
        out.append(blocker)
    return out


def build(stress: dict[str, Any]) -> dict[str, Any]:
    blockers = _dedupe(list(stress.get("blockers", [])))
    items: list[BacklogItem] = []
    for blocker in blockers:
        blocker_id = str(blocker.get("id", "unknown"))
        severity = _norm_severity(blocker.get("severity"))
        patch_class, auto, safe_action, command, evidence = _classify(blocker)
        # Only automatic strengthening/test/report fixes are eligible. Evidence
        # collection and live-data services require operator action.
        if patch_class not in {"bug_fix", "test_or_safety_fix", "report_generation", "observability_improvement"}:
            auto = False
        items.append(BacklogItem(
            item_id=f"HB-{len(items) + 1:03d}",
            severity=severity,
            priority=0,
            source_blocker_id=blocker_id,
            patch_class=patch_class,
            automatic_patch_allowed=auto,
            title=_title(blocker_id),
            rationale=str(blocker.get("required_action") or blocker.get("risk") or safe_action),
            required_evidence=evidence,
            safe_next_action=safe_action,
            validation_command=command,
            forbidden_actions=FORBIDDEN_ACTIONS,
        ))
    items.sort(key=lambda i: (SEVERITY_RANK[i.severity], not i.automatic_patch_allowed, i.source_blocker_id))
    for idx, item in enumerate(items, start=1):
        item.priority = idx
    open_auto = [i for i in items if i.automatic_patch_allowed]
    open_manual = [i for i in items if not i.automatic_patch_allowed]
    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "source_verdict": stress.get("verdict"),
        "source_final_decision": stress.get("final_decision"),
        "item_count": len(items),
        "automatic_patch_candidates": len(open_auto),
        "manual_or_evidence_items": len(open_manual),
        "process_principle": PROCESS_PRINCIPLE,
        "forbidden_actions": FORBIDDEN_ACTIONS,
        "items": [i.to_dict() for i in items],
        "top_item": items[0].to_dict() if items else None,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Improvement Backlog",
        f"_Generated {report['asof']}_",
        "",
        f"- Source verdict: {report.get('source_verdict')}",
        f"- Items: {report['item_count']}",
        f"- Automatic patch candidates: {report['automatic_patch_candidates']}",
        f"- Manual/evidence items: {report['manual_or_evidence_items']}",
        f"- Process: {report['process_principle']}",
        "",
        "## Ranked Items",
    ]
    for item in report["items"]:
        auto = "auto-eligible" if item["automatic_patch_allowed"] else "manual/evidence"
        lines += [
            f"### {item['item_id']} - {item['title']}",
            f"- Severity: {item['severity']}",
            f"- Patch class: {item['patch_class']} ({auto})",
            f"- Source blocker: `{item['source_blocker_id']}`",
            f"- Safe next action: {item['safe_next_action']}",
            f"- Validation: `{item['validation_command']}`",
            f"- Required evidence: {', '.join(item['required_evidence'])}",
            "",
        ]
    lines += [
        "## Forbidden",
        *[f"- {a}" for a in report["forbidden_actions"]],
    ]
    return "\n".join(lines) + "\n"


def load_stress(path: Path | None = None) -> dict[str, Any]:
    p = path or (REPORTS_DIR / "live-readiness-stress.json")
    try:
        return json.loads(p.read_text())
    except Exception:
        return {"verdict": "UNKNOWN", "blockers": []}


def write(report: dict[str, Any]) -> dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    JSON_OUT.write_text(json.dumps(report, indent=2, default=str))
    MD_OUT.write_text(render_md(report))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from-stress", type=Path)
    ap.add_argument("--write-reports", action="store_true")
    args = ap.parse_args(argv)
    report = build(load_stress(args.from_stress))
    if args.write_reports:
        write(report)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
