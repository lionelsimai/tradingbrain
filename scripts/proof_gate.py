#!/usr/bin/env python3
"""TradingBrain proof gate.

This module is intentionally anti-hype. It translates the current evidence pack
into the maximum honest claim TradingBrain may make about itself.

It does not create alpha evidence. It only reads artifacts such as
WORLD-CLASS-READINESS, forward horizon outcomes, and go-live verdicts, then
refuses promotion until actual proof exists.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from paths import ROOT

REPORTS = ROOT / "reports"
OUT_JSON = REPORTS / "proof-gate-latest.json"
OUT_MD = REPORTS / "proof-gate-latest.md"


def _load_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {} if default is None else default


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except Exception:
        return default


def _horizon_rows(scorecard: dict[str, Any]) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in scorecard.get("by_horizon", []) or []:
        try:
            rows[int(row.get("horizon_days"))] = dict(row)
        except Exception:
            continue
    return rows


def _horizon_edge_pass(scorecard: dict[str, Any]) -> tuple[bool, list[str]]:
    rows = _horizon_rows(scorecard)
    missing: list[str] = []
    for h in (1, 5, 20):
        row = rows.get(h)
        if not row:
            missing.append(f"{h}D horizon scorecard row")
            continue
        n = _int(row.get("n"))
        hit = _float(row.get("hit_rate_pct"))
        avg_r = _float(row.get("avg_return_R"))
        if n < 50:
            missing.append(f"{h}D sample >=50 outcomes")
        if hit <= 50.0:
            missing.append(f"{h}D hit rate >50%")
        if avg_r <= 0.0:
            missing.append(f"{h}D average R >0")
    return not missing, missing



def _benchmark_edge_pass(scorecard: dict[str, Any]) -> tuple[bool, list[str]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in scorecard.get("benchmark_adjusted_by_horizon", []) or []:
        try:
            rows[int(row.get("horizon_days"))] = dict(row)
        except Exception:
            continue
    missing: list[str] = []
    for h in (1, 5, 20):
        row = rows.get(h)
        if not row:
            missing.append(f"{h}D benchmark-adjusted scorecard row")
            continue
        n = _int(row.get("n"))
        excess_hit = _float(row.get("excess_hit_rate_pct"))
        avg_excess_r = _float(row.get("avg_excess_return_R"), _float(row.get("avg_excess_return_pct")))
        if n < 50:
            missing.append(f"{h}D benchmark-adjusted sample >=50 outcomes")
        if excess_hit <= 50.0:
            missing.append(f"{h}D excess hit rate >50% versus SPY/QQQ")
        if avg_excess_r <= 0.0:
            missing.append(f"{h}D average excess return >0 versus SPY/QQQ")
    return not missing, missing


def _slippage_adjusted_edge_pass(scorecard: dict[str, Any]) -> tuple[bool, list[str]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in scorecard.get("slippage_adjusted_by_horizon", []) or []:
        try:
            rows[int(row.get("horizon_days"))] = dict(row)
        except Exception:
            continue
    missing: list[str] = []
    for h in (1, 5, 20):
        row = rows.get(h)
        if not row:
            missing.append(f"{h}D slippage-adjusted scorecard row")
            continue
        n = _int(row.get("n"))
        avg_slip_r = _float(
            row.get("avg_slippage_adjusted_return_R"),
            _float(row.get("avg_slippage_adjusted_return_pct")),
        )
        if n < 50:
            missing.append(f"{h}D slippage-adjusted sample >=50 outcomes")
        if avg_slip_r <= 0.0:
            missing.append(f"{h}D slippage-adjusted average R >0")
    return not missing, missing


def evaluate_proof_gate(
    *,
    world: dict[str, Any],
    horizon_scorecard: dict[str, Any],
    go_live: dict[str, Any],
    portfolio_risk: dict[str, Any] | None = None,
    pit_coverage: dict[str, Any] | None = None,
    min_horizon_outcomes: int = 200,
    min_9_horizon_outcomes: int = 500,
) -> dict[str, Any]:
    """Return the maximum honest rating/claim allowed by current evidence."""
    hard_blockers = set(world.get("hard_blockers", []) or [])
    world_rating = _float(world.get("rating_1_to_10"), _float(world.get("overall_score")) / 10.0)
    world_score = _float(world.get("overall_score"), world_rating * 10.0)
    outcomes_total = _int(horizon_scorecard.get("outcomes_total"))
    observations = _int((world.get("counts") or {}).get("forward_paper_observations"))
    resolved_forward = max(
        _int((world.get("counts") or {}).get("forward_paper_resolved")),
        outcomes_total,
    )
    horizon_edge_ok, horizon_missing = _horizon_edge_pass(horizon_scorecard)
    benchmark_edge_ok, benchmark_missing = _benchmark_edge_pass(horizon_scorecard)
    slippage_adjusted_edge_ok, slippage_missing = _slippage_adjusted_edge_pass(horizon_scorecard)
    pit_ok = "survivorship_free_data" not in hard_blockers
    pit_coverage = pit_coverage or {}
    pit_status = str(pit_coverage.get("status", "unknown"))
    candidate_traceable_pct = _float(pit_coverage.get("candidate_traceable_pct"), 0.0)
    candidate_coverage_status = str(pit_coverage.get("candidate_coverage_status", "unknown"))
    candidate_traceability_ok = candidate_traceable_pct >= 95.0
    institutional_pit_ok = pit_ok and pit_status == "closed"
    forward_ok = outcomes_total >= min_horizon_outcomes and bool(horizon_scorecard.get("decision_useful", outcomes_total >= min_horizon_outcomes))
    go_live_verdict = str(go_live.get("verdict", "UNKNOWN"))
    live_ok = go_live_verdict == "CLEARED FOR LIVE"
    portfolio_risk = portfolio_risk or {}
    portfolio_ok = bool(portfolio_risk.get("institutional_risk_budget_ok"))
    regime_count = _int(horizon_scorecard.get("regime_count"), _int(horizon_scorecard.get("market_regime_count"), 0))

    missing: list[str] = []
    if not forward_ok:
        missing.append("200+ resolved 1D/5D/20D horizon outcomes")
    if not horizon_edge_ok:
        missing.extend(horizon_missing)
    if not benchmark_edge_ok:
        missing.extend(benchmark_missing)
    if not slippage_adjusted_edge_ok:
        missing.extend(slippage_missing)
    if not pit_ok:
        missing.append("survivorship/PIT blocker cleared")
    if world_score < 80:
        missing.append("world-class readiness score >=80/100")
    if not live_ok:
        missing.append("go-live gate cleared for any live-trading claim")

    # 8/10 can be a research rating, but only if the actual evidence pack clears
    # forward horizon evidence, raw edge by horizon, benchmark-adjusted edge,
    # slippage/open-adjusted edge, and the world-class PIT blocker. 9/10 further
    # requires the explicit PIT scorecard to be closed and candidate traceability
    # to be institutional-grade.
    proven_8 = forward_ok and horizon_edge_ok and benchmark_edge_ok and slippage_adjusted_edge_ok and pit_ok and world_score >= 80

    missing_9: list[str] = []
    if outcomes_total < min_9_horizon_outcomes:
        missing_9.append("500+ resolved 1D/5D/20D horizon outcomes")
    if regime_count < 3:
        missing_9.append("3+ forward market regimes")
    if not portfolio_ok:
        missing_9.append("institutional portfolio risk budget passing")
    if not institutional_pit_ok:
        missing_9.append("PIT coverage scorecard closed")
    if not candidate_traceability_ok:
        missing_9.append("candidate PIT traceability >=95%")
    if world_score < 90:
        missing_9.append("world-class readiness score >=90/100")
    if not live_ok:
        missing_9.append("go-live gate cleared for 9/10/live-quality claim")
    proven_9 = proven_8 and not missing_9

    if proven_9:
        max_honest_rating = max(9.0, min(9.2, world_rating))
    elif proven_8:
        max_honest_rating = max(8.0, min(8.4, world_rating))
    elif observations >= 25 and "forward_paper_record" in hard_blockers:
        # Current state: machinery exists and observations are being logged, but
        # no resolved proof yet. Do not let the rating drift above 7.
        max_honest_rating = min(7.0, max(6.6, world_rating))
    else:
        max_honest_rating = min(6.8, world_rating if world_rating else 6.5)

    required_next_evidence: list[str] = []
    if not forward_ok:
        required_next_evidence.append(
            "Run daily resolver after market close until 1D/5D/20D horizon outcomes exceed 200."
        )
    if not pit_ok or not institutional_pit_ok:
        required_next_evidence.append(
            "Clear survivorship/PIT blocker with delisted-inclusive point-in-time data."
        )
    if not horizon_edge_ok:
        required_next_evidence.append(
            "Show positive hit-rate and average R on 1D, 5D, and 20D forward horizons."
        )
    if not benchmark_edge_ok:
        required_next_evidence.append(
            "Show positive excess hit-rate and excess return versus SPY/QQQ on 1D, 5D, and 20D horizons."
        )
    if not slippage_adjusted_edge_ok:
        required_next_evidence.append(
            "Show positive first-tradable-open/slippage-adjusted R on 1D, 5D, and 20D horizons."
        )
    if not portfolio_ok:
        required_next_evidence.append("Pass an institutional portfolio risk-budget layer before any 9/10 claim.")
    if outcomes_total < min_9_horizon_outcomes or regime_count < 3:
        required_next_evidence.append(
            "Reach 500+ resolved horizon outcomes across 3+ market regimes before any 9/10 claim."
        )
    if not candidate_traceability_ok:
        required_next_evidence.append("Keep candidate PIT traceability >=95% before any 9/10 claim.")
    if not live_ok:
        required_next_evidence.append("Keep go-live blocked unless a named human signs off after gates pass.")
    if not required_next_evidence:
        required_next_evidence.append("Maintain the full evidence pack; do not weaken proof gates.")

    status = "PROVEN_9_OF_10" if proven_9 else ("PROVEN_8_OF_10" if proven_8 else "NOT_YET_PROVEN")
    return {
        "asof_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "proven_8_of_10": proven_8,
        "proven_9_of_10": proven_9,
        "max_honest_rating": round(max_honest_rating, 1),
        "world_class_rating": round(world_rating, 1),
        "world_class_score": round(world_score, 1),
        "world_class_verdict": world.get("verdict"),
        "hard_blockers": sorted(hard_blockers),
        "forward_observations": observations,
        "resolved_forward_or_horizon_outcomes": resolved_forward,
        "horizon_outcomes_total": outcomes_total,
        "horizon_decision_useful": bool(horizon_scorecard.get("decision_useful", False)),
        "horizon_edge_ok": horizon_edge_ok,
        "benchmark_edge_ok": benchmark_edge_ok,
        "benchmark_adjusted_evidence_present": bool(horizon_scorecard.get("benchmark_adjusted_evidence_present") or horizon_scorecard.get("benchmark_adjusted_by_horizon")),
        "slippage_adjusted_edge_ok": slippage_adjusted_edge_ok,
        "slippage_adjusted_evidence_present": bool(horizon_scorecard.get("slippage_adjusted_by_horizon")),
        "forward_regime_count": regime_count,
        "portfolio_risk_budget_ok": portfolio_ok,
        "portfolio_heat_pct": portfolio_risk.get("portfolio_heat_pct"),
        "pit_coverage_status": pit_status,
        "candidate_traceable_pct": round(candidate_traceable_pct, 1),
        "candidate_coverage_status": candidate_coverage_status,
        "candidate_traceability_ok": candidate_traceability_ok,
        "go_live_verdict": go_live_verdict,
        "live_trading_proven": live_ok,
        "missing_proof": missing,
        "missing_9_proof": missing_9,
        "truth_constraints": [
            "Cannot fabricate time: fresh recommendations only become proof after later market bars exist.",
            "Historical simulation and bootstrapping prove path/risk behavior, not forward alpha by themselves.",
            "Live-trading claims remain forbidden until the independent go-live gate is CLEARED FOR LIVE.",
        ],
        "required_next_evidence": required_next_evidence,
        "disclaimer": "Engineering evidence gate only; not financial advice and not a live-trading authorization.",
    }


def render_markdown(gate: dict[str, Any]) -> str:
    proven8 = "YES" if gate.get("proven_8_of_10") else "NO"
    proven9 = "YES" if gate.get("proven_9_of_10") else "NO"
    live = "YES" if gate.get("live_trading_proven") else "NO"
    lines = [
        f"# TradingBrain Proof Gate — {gate.get('status')}",
        f"_{gate.get('asof_utc')} · max honest rating {gate.get('max_honest_rating')}/10_",
        "",
        f"PROVEN_8_OF_10: **{proven8}**",
        f"PROVEN_9_OF_10: **{proven9}**",
        f"LIVE_TRADING_PROVEN: **{live}**",
        "",
        "## Evidence snapshot",
        f"- World-class readiness: {gate.get('world_class_rating')}/10 ({gate.get('world_class_score')}/100), verdict={gate.get('world_class_verdict')}",
        f"- Forward observations: {gate.get('forward_observations')}",
        f"- Horizon outcomes: {gate.get('horizon_outcomes_total')}, decision-useful={gate.get('horizon_decision_useful')}",
        f"- Horizon edge ok: {gate.get('horizon_edge_ok')}",
        f"- Benchmark-adjusted edge ok: {gate.get('benchmark_edge_ok')}",
        f"- Slippage-adjusted edge ok: {gate.get('slippage_adjusted_edge_ok')}",
        f"- Forward regime count: {gate.get('forward_regime_count')}",
        f"- Portfolio risk budget ok: {gate.get('portfolio_risk_budget_ok')}, heat={gate.get('portfolio_heat_pct')}",
        f"- PIT coverage: {gate.get('pit_coverage_status')} · candidate traceability={gate.get('candidate_traceable_pct')}% ({gate.get('candidate_coverage_status')})",
        f"- Hard blockers: {', '.join(gate.get('hard_blockers') or []) or 'none'}",
        f"- Go-live verdict: {gate.get('go_live_verdict')}",
        "",
        "## Missing proof",
    ]
    missing = gate.get("missing_proof") or []
    lines.extend([f"- {m}" for m in missing] or ["- none"])
    lines += ["", "## Missing 9/10 proof"]
    missing9 = gate.get("missing_9_proof") or []
    lines.extend([f"- {m}" for m in missing9] or ["- none"])
    lines += ["", "## Truth constraints"]
    lines.extend(f"- {c}" for c in gate.get("truth_constraints", []))
    lines += ["", "## Required next evidence"]
    lines.extend(f"- {e}" for e in gate.get("required_next_evidence", []))
    lines += ["", f"_{gate.get('disclaimer', 'Not financial advice.')}_"]
    return "\n".join(lines).rstrip() + "\n"


def build_from_reports() -> dict[str, Any]:
    from lab import world_class
    try:
        from scripts.forward_paper_evidence import write_horizon_scorecard
        horizon = write_horizon_scorecard()
    except Exception:
        horizon = _load_json(REPORTS / "forward-paper-horizon-scorecard-latest.json")
    world = world_class.evaluate()
    go_live = _load_json(REPORTS / "go-live.json")
    portfolio = _load_json(REPORTS / "institutional-portfolio-risk-budget-latest.json")
    if not portfolio:
        try:
            from scripts.institutional_portfolio import build_from_reports as build_portfolio, write_reports as write_portfolio
            portfolio = build_portfolio()
            write_portfolio(portfolio)
        except Exception:
            portfolio = {}
    pit = _load_json(REPORTS / "pit-coverage.json")
    try:
        from scripts.pit_coverage import compute_pit_coverage, write_reports as write_pit_reports
        pit = compute_pit_coverage()
        write_pit_reports(pit)
    except Exception:
        pit = pit or {}
    return evaluate_proof_gate(world=world, horizon_scorecard=horizon, go_live=go_live, portfolio_risk=portfolio, pit_coverage=pit)


def write_reports(gate: dict[str, Any] | None = None) -> dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    gate = gate or build_from_reports()
    OUT_JSON.write_text(json.dumps(gate, indent=2, default=str))
    OUT_MD.write_text(render_markdown(gate))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="TradingBrain anti-hype proof gate")
    ap.add_argument("--json", action="store_true", help="Print JSON")
    args = ap.parse_args(argv)
    gate = build_from_reports()
    write_reports(gate)
    print(json.dumps(gate, indent=2, default=str) if args.json else render_markdown(gate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
