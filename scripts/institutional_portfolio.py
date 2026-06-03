#!/usr/bin/env python3
"""Institutional-style portfolio risk budget for research/paper candidates.

This module never submits orders. It reads the latest recommendation artifacts,
sizes the candidates under the canonical risk policy, and writes a portfolio
heat/bucket/rejection report for proof-gate and dashboard use.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import REPORTS_DIR
from safety import risk_policy

REPORTS = REPORTS_DIR
OUT_JSON = REPORTS / "institutional-portfolio-risk-budget-latest.json"
OUT_MD = REPORTS / "institutional-portfolio-risk-budget-latest.md"
DISCLAIMER = "Research/paper-only portfolio risk budget. No orders are submitted."


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _candidate_symbol(candidate: dict[str, Any]) -> str:
    return str(candidate.get("ticker") or candidate.get("symbol") or "").upper().strip()


def _entry(candidate: dict[str, Any]) -> float | None:
    zone = candidate.get("entry_zone")
    if isinstance(zone, dict):
        low = zone.get("low")
        high = zone.get("high")
        try:
            if low is not None and high is not None:
                return (float(low) + float(high)) / 2.0
            if low is not None:
                return float(low)
            if high is not None:
                return float(high)
        except Exception:
            return None
    for key in ("entry", "price", "last", "close"):
        try:
            if candidate.get(key) is not None:
                return float(candidate[key])
        except Exception:
            return None
    return None


def _target(candidate: dict[str, Any]) -> float | None:
    targets = candidate.get("targets")
    if isinstance(targets, list) and targets:
        first = targets[0]
        try:
            if isinstance(first, dict):
                return float(first.get("level"))
            return float(first)
        except Exception:
            return None
    for key in ("target", "take_profit", "t1"):
        try:
            if candidate.get(key) is not None:
                return float(candidate[key])
        except Exception:
            return None
    return None


def _load_candidates(report_dir: Path = REPORTS) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: dict[str, Any], source: str) -> None:
        symbol = _candidate_symbol(row)
        if not symbol or symbol in seen:
            return
        item = dict(row)
        item["ticker"] = symbol
        item["_source_report"] = source
        seen.add(symbol)
        out.append(item)

    for name in ("recommendations.json", "smart-recommendations.json", "super-smart-recommendations.json"):
        data = _json(report_dir / name, {})
        for row in data.get("picks") or []:
            if isinstance(row, dict):
                add(row, name)
        # strict_current_picks may contain symbols only. Use a conservative shell.
        for symbol in data.get("strict_current_picks") or []:
            add({"ticker": symbol, "conviction_score": 60}, name)

    return out


def _bucket(candidate: dict[str, Any]) -> str:
    try:
        conviction = float(candidate.get("conviction_score") or candidate.get("score") or 0)
    except Exception:
        conviction = 0.0
    if conviction >= 80:
        return "core"
    if conviction >= 60:
        return "satellite"
    return "watch"


def _risk_row(candidate: dict[str, Any], *, equity: float) -> dict[str, Any]:
    policy = risk_policy.load()
    tr = policy["trade_risk"]
    pr = policy["portfolio_risk"]
    symbol = _candidate_symbol(candidate)
    entry = _entry(candidate)
    stop = candidate.get("stop_loss") if candidate.get("stop_loss") is not None else candidate.get("stop")
    target = _target(candidate)
    rejects: list[str] = []
    if entry is None or entry <= 0:
        rejects.append("entry missing or invalid")
    try:
        stop_f = float(stop)
    except Exception:
        stop_f = None
    if stop_f is None or stop_f <= 0:
        rejects.append("stop missing or invalid")
    if entry is not None and stop_f is not None and stop_f >= entry:
        rejects.append("long stop must be below entry")
    if target is None or target <= 0:
        rejects.append("target missing or invalid")

    risk_per_share = abs(float(entry or 0) - float(stop_f or 0))
    reward_risk = None
    if entry and stop_f and target and risk_per_share > 0:
        reward_risk = round((float(target) - float(entry)) / risk_per_share, 3)
        if reward_risk < float(tr["min_reward_to_risk"]):
            rejects.append(f"reward:risk {reward_risk} below policy {tr['min_reward_to_risk']}")

    max_risk_pct = float(tr["risk_per_trade_pct"])
    desired_risk = equity * max_risk_pct / 100.0
    shares = int(desired_risk / risk_per_share) if risk_per_share > 0 else 0
    if shares <= 0:
        rejects.append("position rounds to zero")
    notional = shares * float(entry or 0)
    risk_dollars = shares * risk_per_share
    position_pct = notional / equity * 100.0 if equity > 0 else 0.0
    risk_pct = risk_dollars / equity * 100.0 if equity > 0 else 0.0
    if position_pct > float(tr["max_position_pct"]):
        rejects.append(f"position {position_pct:.2f}% exceeds max {tr['max_position_pct']}%")
    if risk_pct > float(tr["max_risk_per_trade_pct"]):
        rejects.append(f"risk {risk_pct:.2f}% exceeds max {tr['max_risk_per_trade_pct']}%")
    if symbol == "":
        rejects.append("ticker missing")

    return {
        "ticker": symbol,
        "source_report": candidate.get("_source_report"),
        "bucket": _bucket(candidate),
        "entry": round(float(entry), 4) if entry is not None else None,
        "stop": round(float(stop_f), 4) if stop_f is not None else None,
        "target": round(float(target), 4) if target is not None else None,
        "shares": shares,
        "notional": round(notional, 2),
        "position_pct": round(position_pct, 3),
        "risk_dollars": round(risk_dollars, 2),
        "risk_pct": round(risk_pct, 3),
        "reward_risk": reward_risk,
        "accepted": not rejects,
        "reject_reasons": rejects,
    }


def build_from_reports(*, equity: float | None = None, report_dir: Path = REPORTS) -> dict[str, Any]:
    policy = risk_policy.load()
    tr = policy["trade_risk"]
    pr = policy["portfolio_risk"]
    equity = float(equity or policy["account"].get("default_equity_usd", 50000))
    candidates = _load_candidates(report_dir)
    rows = [_risk_row(c, equity=equity) for c in candidates]
    accepted = [r for r in rows if r["accepted"]]
    rejected = [r for r in rows if not r["accepted"]]
    portfolio_heat_pct = round(sum(float(r["risk_pct"]) for r in accepted), 3)
    gross_exposure_pct = round(sum(float(r["position_pct"]) for r in accepted), 3)
    max_position_risk_pct = round(max([float(r["risk_pct"]) for r in accepted] or [0.0]), 3)
    max_position_pct = round(max([float(r["position_pct"]) for r in accepted] or [0.0]), 3)
    bucket_heat: dict[str, float] = {}
    for row in accepted:
        bucket_heat[row["bucket"]] = round(bucket_heat.get(row["bucket"], 0.0) + float(row["risk_pct"]), 3)

    blockers: list[str] = []
    if not candidates:
        blockers.append("no current recommendation candidates found")
    if len(accepted) > int(pr["max_concurrent_positions"]):
        blockers.append(f"accepted candidates exceed max concurrent {pr['max_concurrent_positions']}")
    if portfolio_heat_pct > float(pr["max_portfolio_heat_pct"]):
        blockers.append(f"portfolio heat {portfolio_heat_pct}% exceeds max {pr['max_portfolio_heat_pct']}%")
    if gross_exposure_pct > float(tr["max_position_pct"]) * max(1, int(pr["max_concurrent_positions"])):
        blockers.append("gross exposure exceeds simple portfolio position cap envelope")
    if max_position_risk_pct > float(tr["max_risk_per_trade_pct"]):
        blockers.append(f"single-position risk {max_position_risk_pct}% exceeds max {tr['max_risk_per_trade_pct']}%")
    if rejected:
        blockers.append(f"{len(rejected)} candidate(s) rejected by institutional budget checks")

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "mode": "paper_research_risk_budget",
        "equity": equity,
        "institutional_risk_budget_ok": not blockers and bool(accepted),
        "portfolio_heat_pct": portfolio_heat_pct,
        "gross_exposure_pct": gross_exposure_pct,
        "max_position_risk_pct": max_position_risk_pct,
        "max_position_pct": max_position_pct,
        "policy_limits": {
            "risk_per_trade_pct": tr["risk_per_trade_pct"],
            "max_risk_per_trade_pct": tr["max_risk_per_trade_pct"],
            "max_position_pct": tr["max_position_pct"],
            "max_portfolio_heat_pct": pr["max_portfolio_heat_pct"],
            "max_concurrent_positions": pr["max_concurrent_positions"],
            "min_reward_to_risk": tr["min_reward_to_risk"],
        },
        "bucket_heat_pct": bucket_heat,
        "accepted_candidates": accepted,
        "rejected_candidates": rejected,
        "blockers": blockers,
        "required_next_actions": [
            "Keep portfolio heat within canonical policy before paper entries.",
            "Reject any candidate without stop, target, valid reward:risk, or non-zero position size.",
            "Use this report as research evidence only; execution still goes through OrderManager.",
        ],
        "disclaimer": DISCLAIMER,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        f"# Institutional Portfolio Risk Budget - {'PASS' if report.get('institutional_risk_budget_ok') else 'BLOCKED'}",
        "",
        f"Generated: {report.get('asof')}",
        f"Equity: ${report.get('equity'):,.2f}",
        f"Portfolio heat: {report.get('portfolio_heat_pct')}%",
        f"Gross exposure: {report.get('gross_exposure_pct')}%",
        f"Accepted candidates: {len(report.get('accepted_candidates', []))}",
        f"Rejected candidates: {len(report.get('rejected_candidates', []))}",
        "",
        "## Blockers",
    ]
    lines.extend([f"- {b}" for b in report.get("blockers", [])] or ["- none"])
    lines += ["", "## Accepted"]
    for row in report.get("accepted_candidates", []):
        lines.append(
            f"- {row['ticker']}: risk={row['risk_pct']}%, notional={row['position_pct']}%, R:R={row['reward_risk']}"
        )
    lines += ["", "## Rejected"]
    for row in report.get("rejected_candidates", []):
        lines.append(f"- {row['ticker']}: {', '.join(row.get('reject_reasons', []))}")
    lines += ["", report.get("disclaimer", DISCLAIMER)]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any] | None = None, *, equity: float | None = None) -> dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or build_from_reports(equity=equity)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render_md(report))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Research/paper institutional portfolio risk budget")
    ap.add_argument("--equity", type=float)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = build_from_reports(equity=args.equity)
    write_reports(report)
    print(json.dumps(report, indent=2, default=str) if args.json else render_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
