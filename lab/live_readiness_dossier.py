#!/usr/bin/env python3
"""Generate the human live-readiness dossier from current evidence reports."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import REPORTS_DIR


DOSSIER = REPORTS_DIR / "live-readiness-dossier.md"


def _load(report_dir: Path, name: str) -> dict[str, Any]:
    path = report_dir / name
    if not path.exists():
        return {"missing": True, "path": str(path)}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return {"missing": False, "invalid": True, "path": str(path), "error": str(exc)}


def _status(obj: dict[str, Any], key: str = "verdict") -> str:
    if obj.get("missing"):
        return "MISSING"
    if obj.get("invalid"):
        return "INVALID"
    return str(obj.get(key) or obj.get("status") or obj.get("verdict") or "UNKNOWN")


def _list(items: list[Any]) -> list[str]:
    if not items:
        return ["- None recorded."]
    out = []
    for item in items:
        if isinstance(item, dict):
            ident = item.get("id") or item.get("gate") or item.get("title") or "item"
            sev = item.get("severity") or item.get("status") or "unknown"
            action = item.get("required_action") or item.get("detail") or item.get("fix") or ""
            out.append(f"- {ident}: {sev}. {action}".rstrip())
        else:
            out.append(f"- {item}")
    return out


def build_markdown(report_dir: Path = REPORTS_DIR) -> str:
    readiness = _load(report_dir, "live-readiness-dashboard.json")
    stress = _load(report_dir, "live-readiness-stress.json")
    go_live = _load(report_dir, "go-live.json")
    data_quality = _load(report_dir, "data-quality.json")
    monte_carlo = _load(report_dir, "monte-carlo.json")
    walk_forward = _load(report_dir, "walk-forward.json")
    gauntlet = _load(report_dir, "gauntlet.json")
    paper = _load(report_dir, "scorecard-paper.json")
    live = _load(report_dir, "scorecard-live.json")
    replay = _load(report_dir, "scorecard-replay.json")
    circuit = _load(report_dir, "circuit-breakers.json")
    red_team = _load(report_dir, "red-team-live-readiness.json")

    paper_summary = readiness.get("paper_evidence_summary", {})
    blockers = readiness.get("blockers") or stress.get("blockers") or []
    incidents = readiness.get("open_incidents", [])
    stress_categories = stress.get("categories", {})

    lines = [
        "# TradingBrain Live-Readiness Dossier",
        f"_generated {datetime.now(timezone.utc).isoformat()}_",
        "",
        "## 1. Executive verdict",
        f"- Verdict: {_status(readiness)}",
        f"- Stress verdict: {_status(stress)}",
        f"- Final decision: {stress.get('final_decision', 'UNKNOWN')}",
        f"- Overall score: {stress.get('overall_score', 'UNKNOWN')}",
        f"- Biggest blocker: {(stress.get('biggest_blocker') or {}).get('id', 'UNKNOWN')}",
        "",
        "## 2. Current mode",
        f"- Mode: {readiness.get('mode', 'UNKNOWN')}",
        f"- Live trading enabled: {readiness.get('live_trading_enabled', False)}",
        "",
        "## 3. Go-live gate table",
    ]
    gates = go_live.get("gates") if isinstance(go_live.get("gates"), list) else []
    lines += ["| Gate | Status | Detail |", "|---|---|---|"]
    for gate in gates:
        lines.append(f"| {gate.get('gate', '?')} | {gate.get('status', '?')} | {gate.get('detail', '')} |")
    if not gates:
        lines.append("| Go-live report | MISSING | Generate reports/go-live.json. |")

    lines += [
        "",
        "## 4. Evidence source table",
        "| Source | Resolved | Open | Verdict |",
        "|---|---:|---:|---|",
        f"| Paper | {paper_summary.get('paper_resolved', 0)} | {paper_summary.get('paper_open', 0)} | {paper_summary.get('paper_verdict', _status(paper))} |",
        f"| Live | {paper_summary.get('live_resolved', 0)} | {paper_summary.get('live_open', 0)} | {paper_summary.get('live_verdict', _status(live))} |",
        f"| Replay | {paper_summary.get('replay_resolved', 0)} | 0 | {paper_summary.get('replay_verdict', _status(replay))} |",
        "",
        "## 5. Paper record summary",
        f"- Resolved forward paper trades: {paper_summary.get('paper_resolved', 0)}",
        f"- Open forward paper trades: {paper_summary.get('paper_open', 0)}",
        "- Replay/backtest evidence is not counted as forward paper evidence.",
        "",
        "## 6. Strategy scorecards",
        f"- Paper scorecard: {_status(paper)}",
        f"- Live scorecard: {_status(live)}",
        f"- Replay scorecard: {_status(replay)}",
        "",
        "## 7. Backtest realism summary",
        f"- Gauntlet verdict: {_status(gauntlet)}",
        f"- Gauntlet score: {gauntlet.get('overall_score', 'UNKNOWN')}",
        f"- Backtest realism stress score: {stress.get('backtest_realism_score', 'UNKNOWN')}",
        "",
        "## 8. Monte Carlo summary",
        f"- Status: {_status(monte_carlo, 'pass')}",
        f"- Evidence source: {monte_carlo.get('source', 'UNKNOWN')}",
        f"- P99 drawdown: {(monte_carlo.get('max_drawdown_pct_approx') or {}).get('p99', 'UNKNOWN')}",
        "",
        "## 9. Walk-forward summary",
        f"- Status: {_status(walk_forward, 'pass')}",
        f"- Verdict: {walk_forward.get('verdict', 'UNKNOWN')}",
        "",
        "## 10. Overfitting summary",
        "- Go-live gate 4 remains the authority for overfitting status.",
        *[f"- {b}" for b in go_live.get("blockers", []) if "Overfitting" in str(b)],
        "",
        "## 11. Data quality summary",
        f"- Pass: {data_quality.get('pass', 'UNKNOWN')}",
        f"- Hard failures: {len(data_quality.get('hard_failures', [])) if isinstance(data_quality.get('hard_failures'), list) else 'UNKNOWN'}",
        f"- Trust level: {data_quality.get('trust_level', 'UNKNOWN')}",
        "",
        "## 12. Execution stress summary",
        f"- Execution score: {stress.get('execution_score', 'UNKNOWN')}",
        f"- Execution cases failed: {(stress_categories.get('execution') or {}).get('fail', 'UNKNOWN')}",
        "",
        "## 13. Broker chaos summary",
        f"- Broker chaos score: {stress.get('broker_chaos_score', 'UNKNOWN')}",
        "- Fake broker chaos uses the order manager path; direct production submits remain forbidden.",
        "",
        "## 14. Reconciliation summary",
        f"- Reconciliation score: {stress.get('reconciliation_score', 'UNKNOWN')}",
        "",
        "## 15. Incident summary",
        f"- Open incidents: {len(incidents) if isinstance(incidents, list) else 'UNKNOWN'}",
        *_list(incidents if isinstance(incidents, list) else []),
        "",
        "## 16. Kill-switch summary",
        f"- Circuit-breaker report: {_status(circuit, 'pass')}",
        "- Kill switch is checked by config_guard and risk_gate, and critical incidents engage it.",
        "",
        "## 17. Approval summary",
        *_list(readiness.get("approval_status", [])),
        "",
        "## 18. Observability summary",
        f"- Observability score: {stress.get('observability_score', 'UNKNOWN')}",
        f"- Dashboard report: {_status(readiness)}",
        "",
        "## 19. Dashboard truthfulness check",
        f"- Research-only warning: {readiness.get('research_only_warning', True)}",
        "- Dashboard must not show live-ready while go-live is blocked.",
        "",
        "## 20. Red-team findings",
        f"- Red-team report: {_status(red_team)}",
        f"- Findings: {red_team.get('finding_count', 'UNKNOWN')}",
        f"- Blocking findings: {red_team.get('blocking_count', 'UNKNOWN')}",
        "- Red-team safety tests are part of the pytest suite.",
        "",
        "## 21. Remaining blockers",
        *_list(blockers if isinstance(blockers, list) else []),
        "",
        "## 22. Required next actions",
        f"- Safe next action: {readiness.get('safe_next_action', 'Run live-like paper mode and collect forward evidence.')}",
        f"- Forbidden next action: {readiness.get('forbidden_next_action', 'Do not enable live trading or bypass gates.')}",
        "",
        "## 23. Final verdict",
        f"- Final verdict: {_status(readiness)}",
        f"- Current mode: {readiness.get('mode', 'UNKNOWN')}",
        f"- Go-live status: {readiness.get('go_live_status', 'UNKNOWN')}",
        "- This dossier is an evidence pack, not a live-trading approval.",
        "",
    ]
    return "\n".join(lines)


def write_dossier(report_dir: Path = REPORTS_DIR, out_path: Path | None = None) -> Path:
    out = out_path or (report_dir / "live-readiness-dossier.md")
    report_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(build_markdown(report_dir))
    return out


def main() -> None:
    path = write_dossier()
    print(path)


if __name__ == "__main__":
    main()
