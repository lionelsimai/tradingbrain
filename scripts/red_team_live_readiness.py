#!/usr/bin/env python3
"""Adversarial live-readiness red team.

This script attacks the evidence pack, not the profit story. It writes a JSON
finding set that blocks live readiness when proof is missing or overclaimed.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import REPORTS_DIR


OUT = REPORTS_DIR / "red-team-live-readiness.json"


@dataclass
class Finding:
    id: str
    severity: str
    title: str
    evidence: str
    attack_path: str
    expected_damage: str
    fix: str
    test: str
    blocks_live: bool


def _load(name: str) -> dict[str, Any]:
    p = REPORTS_DIR / name
    if not p.exists():
        return {"missing": True}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        return {"invalid": True, "error": str(exc)}


def _sev(blocks: bool, default: str = "medium") -> str:
    return "critical" if blocks else default


def run() -> dict[str, Any]:
    go = _load("go-live.json")
    dash = _load("live-readiness-dashboard.json")
    stress = _load("live-readiness-stress.json")
    paper = _load("scorecard-paper.json")
    replay = _load("scorecard-replay.json")
    data_quality = _load("data-quality.json")

    paper_resolved = int(
        (dash.get("paper_evidence_summary") or {}).get("paper_resolved")
        or paper.get("resolved")
        or paper.get("overall", {}).get("n")
        or 0
    )
    replay_resolved = int(
        (dash.get("paper_evidence_summary") or {}).get("replay_resolved")
        or replay.get("resolved")
        or replay.get("overall", {}).get("n")
        or 0
    )
    go_blocked = go.get("verdict") != "CLEARED FOR LIVE"
    dashboard_overclaims = dash.get("verdict") in {"LIVE_REVIEW_CANDIDATE", "LIVE_LIKE_PAPER_READY"} and go_blocked
    stress_blocked = stress.get("verdict") == "LIVE_BLOCKED"

    attacks = [
        ("RT-LIVE-001", "Backtest overconfidence", go_blocked,
         f"go-live verdict={go.get('verdict')}; blockers={go.get('blockers')}",
         "Treat a blocked report as deployable because replay looks profitable.",
         "Capital allocated to an unproven edge.", "Keep final verdict blocked until all gates clear.",
         "python -m lab.go_live --json"),
        ("RT-LIVE-002", "Insufficient paper evidence", paper_resolved < 200,
         f"resolved_forward_paper={paper_resolved}",
         "Use replay or open paper positions as resolved paper evidence.",
         "Live sizing before fill quality and drift are known.", "Collect 200 resolved forward paper observations.",
         "python -m loops.forward_paper_runner --scorecard"),
        ("RT-LIVE-003", "Survivorship bias", True,
         "delisted-inclusive point-in-time universe proof not present",
         "Accept a surviving-name universe as live-like.",
         "Inflated expectancy and understated drawdown.", "Add delisted-inclusive PIT universe report.",
         "python -m scripts.validate_all"),
        ("RT-LIVE-004", "Point-in-time data gap", True,
         "PIT universe validation is not proven in live-readiness dossier",
         "Use future-available symbols or corporate actions in validation.",
         "Hidden lookahead and false deploy verdict.", "Add PIT source provenance and tests.",
         "python -m lab.live_readiness_dossier"),
        ("RT-LIVE-005", "Unrealistic fills", paper_resolved < 50,
         f"resolved paper fills={paper_resolved}",
         "Assume backtest fills match broker paper fills.",
         "Slippage and partial fills erase edge.", "Collect broker-sandbox/paper fill records.",
         "python -m loops.forward_paper_runner --once"),
        ("RT-LIVE-006", "Hidden lookahead", False,
         f"validate pass={_load('validate.json').get('pass')}",
         "Rely on validation without checking the report exists and passes.",
         "Future data leaks into strategy selection.", "Keep no-lookahead validation in CI.",
         "python -m lab.validate"),
        ("RT-LIVE-007", "Cost underestimation", stress_blocked,
         f"backtest realism score={stress.get('backtest_realism_score')}",
         "Accept base costs but skip stressed costs.",
         "Edge vanishes once commissions/spread/slippage rise.", "Keep cost stress in gauntlet.",
         "python -m lab.live_readiness_stress --all --write-reports"),
        ("RT-LIVE-008", "Slippage underestimation", paper_resolved < 50,
         "paper slippage sample is thin",
         "Size up before observed slippage distribution exists.",
         "Stops and targets perform worse than expected.", "Track slippage average and p95 in paper scorecard.",
         "python -m loops.forward_paper_runner --scorecard"),
        ("RT-LIVE-009", "Regime overfitting", "4. Overfitting checks" in str(go.get("blockers")),
         f"go-live blockers={go.get('blockers')}",
         "Deploy a strategy with large IS/OOS gap.",
         "Strategy fails outside fitted regime.", "Reduce parameter fragility and rerun walk-forward.",
         "python -m pytest -q tests/test_gauntlet.py"),
        ("RT-LIVE-010", "Sample-size weakness", paper_resolved < 200,
         f"resolved_forward_paper={paper_resolved}; replay_resolved={replay_resolved}",
         "Replace true paper sample size with replay sample size.",
         "Confidence is unsupported by live-like evidence.", "Accumulate forward evidence across regimes.",
         "python -m safety.live_readiness"),
        ("RT-LIVE-011", "Execution weakness", stress.get("execution_score", 0) < 100,
         f"execution_score={stress.get('execution_score')}",
         "Ignore broker rejection, partial fill, or unknown-status cases.",
         "Duplicate orders or unprotected positions.", "Keep broker chaos stress green.",
         "python -m pytest -q tests/test_fake_broker_chaos.py"),
        ("RT-LIVE-012", "Broker integration weakness", paper_resolved < 50,
         "paper broker forward evidence is still thin",
         "Assume sandbox behavior from in-memory simulation only.",
         "Live broker state diverges from internal state.", "Add sandbox adapter evidence before live review.",
         "python -m loops.forward_paper_runner --once"),
        ("RT-LIVE-013", "Reconciliation weakness", stress.get("reconciliation_score", 0) < 100,
         f"reconciliation_score={stress.get('reconciliation_score')}",
         "Trust internal state after broker mismatch.",
         "Ghost/missing positions remain tradable.", "Expand reconciliation chaos matrix.",
         "python -m pytest -q tests/test_reconciliation.py"),
        ("RT-LIVE-014", "Stop-loss weakness", False,
         "protective-order tests and chaos incidents present",
         "Allow an entry or fill without stop protection.",
         "Undefined downside and emergency manual repair.", "Keep critical incident on stop attach failure.",
         "python -m pytest -q tests/test_fake_broker_chaos.py"),
        ("RT-LIVE-015", "Kill-switch weakness", False,
         "config_guard and risk_gate check kill switch",
         "Ignore unreadable or engaged kill switch.",
         "Orders continue through emergency halt.", "Keep fail-closed kill switch tests.",
         "python -m pytest -q tests/test_safety.py"),
        ("RT-LIVE-016", "Approval weakness", "7. Human approval" in str(go.get("blockers")),
         f"approval_status={(dash.get('approval_status') or go.get('gates'))}",
         "Accept stale, anonymous, or hash-mismatched approval.",
         "Live trading starts without accountable review.", "Require named approver and current pack hash.",
         "python -m lab.go_live --json"),
        ("RT-LIVE-017", "Logging weakness", stress.get("observability_score", 0) < 100,
         f"observability_score={stress.get('observability_score')}",
         "Incident or rejection occurs without durable audit trail.",
         "Cannot reconstruct fault or improve safely.", "Add event-level observability tests.",
         "python -m lab.live_readiness_stress --all --write-reports"),
        ("RT-LIVE-018", "Dashboard overclaiming", dashboard_overclaims,
         f"dashboard verdict={dash.get('verdict')}; go-live={go.get('verdict')}",
         "Show live-ready while the authority is blocked.",
         "Operator trusts a false green dashboard.", "Dashboard must mirror live_readiness authority.",
         "python -m monitoring.live_readiness_dashboard"),
        ("RT-LIVE-019", "AI hallucination", True,
         "AI proposal schema/source validation is not yet complete",
         "Let an agent invent quote, earnings, or confidence evidence.",
         "Risk gate receives false facts.", "Add strict AI proposal schema and source checks.",
         "python -m pytest -q tests/test_agent_permissions.py"),
        ("RT-LIVE-020", "Live-readiness overstatement", go_blocked,
         f"go-live={go.get('verdict')}; stress_final={stress.get('final_decision')}",
         "Summarize RESEARCH_ONLY as live-ready.",
         "Premature real-money deployment.", "Default final verdict to LIVE_BLOCKED.",
         "python -m lab.live_readiness_dossier"),
    ]

    findings = [
        Finding(
            id=ident,
            severity=_sev(bool(blocks), "low"),
            title=title,
            evidence=str(evidence),
            attack_path=attack_path,
            expected_damage=damage,
            fix=fix,
            test=test,
            blocks_live=bool(blocks),
        )
        for ident, title, blocks, evidence, attack_path, damage, fix, test in attacks
    ]
    out = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "verdict": "LIVE_BLOCKED" if any(f.blocks_live for f in findings) else "NO_RED_TEAM_BLOCKERS",
        "finding_count": len(findings),
        "blocking_count": sum(1 for f in findings if f.blocks_live),
        "findings": [asdict(f) for f in findings],
        "data_quality_pass": data_quality.get("pass"),
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, sort_keys=True, default=str))
    return out


def main() -> None:
    print(json.dumps(run(), indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
