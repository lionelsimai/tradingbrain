#!/usr/bin/env python3
"""Target-quality context for research candidates.

This is a skepticism layer for TradingBrain targets. It combines the technical
trade plan (entry, stop, reward/risk, modeled upside) with analyst-target
provenance. Missing or aggregate-only analyst evidence caps confidence; it never
turns a target into a prediction.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from paths import CONFIG_DIR, KNOWLEDGE_DB, REPORTS_DIR
from scripts.analyst_target_provenance import build_scorecard as build_provenance_scorecard

REPORTS = REPORTS_DIR
KB = KNOWLEDGE_DB
CONFIG = CONFIG_DIR / "target_quality.yaml"
OUT_JSON = REPORTS / "target-quality-latest.json"
OUT_MD = REPORTS / "target-quality-latest.md"

DISCLAIMER = (
    "Target quality is research-only. It checks whether a target scenario is "
    "defined-risk and independently contextualized; it is not a prediction, "
    "financial advice, or an instruction to trade."
)

DEFAULT_POLICY = {
    "technical_target_quality": {
        "min_reward_risk_for_research_candidate": 1.5,
        "min_reward_risk_for_clean_candidate": 2.0,
        "max_target_extension_atr": 4.0,
        "require_target_below_extreme_52w_extension": True,
    },
    "verdicts": {
        "live_quality_blocked": "Research only: live-quality confidence blocked. Use watchlist/paper mode.",
        "target_untrusted": "Target not independently trustworthy; treat as scenario only.",
        "target_supported": "Target has enough independent support for research use, still not a prediction.",
    },
}


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _read_policy(path: Path = CONFIG) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text()) or {}
    except Exception:
        raw = {}
    policy = json.loads(json.dumps(DEFAULT_POLICY))
    for section, values in raw.items():
        if isinstance(values, dict) and isinstance(policy.get(section), dict):
            policy[section].update(values)
        else:
            policy[section] = values
    return policy


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _round(value: Any, digits: int = 3) -> float | None:
    f = _float(value)
    return round(f, digits) if f is not None else None


def _ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def _as_tickers(value: list[str] | str | None) -> list[str]:
    out: list[str] = []

    def add(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, str):
            for part in item.replace(",", " ").split():
                t = _ticker(part)
                if t and t not in out:
                    out.append(t)
            return
        if isinstance(item, dict):
            add(item.get("ticker") or item.get("symbol"))
            return
        if isinstance(item, (list, tuple)):
            for child in item:
                add(child)

    add(value)
    return out


def _entry(row: dict[str, Any]) -> float | None:
    zone = row.get("entry_zone")
    if isinstance(zone, dict):
        low = _float(zone.get("low"))
        high = _float(zone.get("high"))
        if low is not None and high is not None:
            return (low + high) / 2.0
        return low if low is not None else high
    for key in ("entry", "entry_price", "last_close", "close", "price"):
        f = _float(row.get(key))
        if f is not None:
            return f
    return None


def _target(row: dict[str, Any]) -> float | None:
    targets = row.get("targets")
    if isinstance(targets, list) and targets:
        first = targets[0]
        if isinstance(first, dict):
            f = _float(first.get("level") or first.get("target") or first.get("price"))
            if f is not None:
                return f
        f = _float(first)
        if f is not None:
            return f
    for key in ("target", "target_price", "take_profit", "t1"):
        f = _float(row.get(key))
        if f is not None:
            return f
    return None


def _stop(row: dict[str, Any]) -> float | None:
    for key in ("stop_loss", "stop", "invalidation_price"):
        f = _float(row.get(key))
        if f is not None:
            return f
    return None


def _reward_risk(row: dict[str, Any], entry: float | None, stop: float | None, target: float | None) -> float | None:
    explicit = _float(row.get("reward_to_risk") or row.get("reward_risk"))
    if explicit is not None:
        return explicit
    if entry is None or stop is None or target is None:
        return None
    risk = entry - stop
    if risk <= 0:
        return None
    return (target - entry) / risk


def _modeled_upside(entry: float | None, target: float | None, row: dict[str, Any]) -> float | None:
    explicit = _float(row.get("target_upside_pct") or row.get("modeled_upside_pct"))
    if explicit is not None:
        return explicit
    if entry and target:
        return (target - entry) / entry * 100.0
    return None


def _load_candidates(report_dir: Path = REPORTS) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(row: Any, source: str) -> None:
        if isinstance(row, str):
            item = {"ticker": row}
        elif isinstance(row, dict):
            item = dict(row)
        else:
            return
        symbol = _ticker(item.get("ticker") or item.get("symbol"))
        if not symbol or symbol in seen:
            return
        item["ticker"] = symbol
        item["_source_report"] = source
        seen.add(symbol)
        out.append(item)

    for name in (
        "recommendations.json",
        "forecast-recommendations-latest.json",
        "smart-recommendations.json",
        "super-smart-recommendations.json",
    ):
        data = _read_json(report_dir / name, {})
        for row in data.get("picks") or []:
            add(row, name)
        for row in data.get("watch_list") or []:
            add(row, name)
        for symbol in data.get("strict_current_picks") or []:
            add(symbol, name)
    return out


def _technical_context(row: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    technical = policy.get("technical_target_quality") or {}
    min_research = float(technical.get("min_reward_risk_for_research_candidate", 1.5))
    min_clean = float(technical.get("min_reward_risk_for_clean_candidate", 2.0))
    entry = _entry(row)
    stop = _stop(row)
    target = _target(row)
    rr = _reward_risk(row, entry, stop, target)
    upside = _modeled_upside(entry, target, row)
    cautions: list[str] = []
    blocks: list[str] = []
    if entry is None or entry <= 0:
        blocks.append("entry missing or invalid")
    if stop is None or stop <= 0:
        blocks.append("stop missing or invalid")
    if target is None or target <= 0:
        blocks.append("target missing or invalid")
    if entry is not None and stop is not None and stop >= entry:
        blocks.append("long stop must be below entry")
    if rr is None:
        blocks.append("reward:risk unavailable")
    elif rr < min_research:
        blocks.append(f"reward:risk {rr:.2f} below research minimum {min_research:.2f}")
    elif rr < min_clean:
        cautions.append(f"reward:risk {rr:.2f} below clean-candidate threshold {min_clean:.2f}")
    if upside is not None and upside > 50:
        cautions.append(f"modeled upside {upside:.1f}% is aggressive; require stronger proof before raising confidence")
    return {
        "entry": _round(entry, 4),
        "stop": _round(stop, 4),
        "target": _round(target, 4),
        "reward_risk": _round(rr, 3),
        "modeled_upside_pct": _round(upside, 2),
        "technical_blocks": blocks,
        "technical_cautions": cautions,
        "technical_status": "blocked" if blocks else ("clean" if rr is not None and rr >= min_clean else "usable_with_caution"),
    }


def _row_verdict(technical: dict[str, Any], provenance: dict[str, Any]) -> tuple[str, str, list[str]]:
    cautions = list(technical.get("technical_cautions") or [])
    cautions.extend(provenance.get("cautions") or [])
    if technical.get("technical_blocks"):
        cautions.extend(technical["technical_blocks"])
        return "target_untrusted", "low", cautions

    status = str(provenance.get("status") or "missing")
    if status in {"missing", "stale"}:
        cautions.append("No analyst-target provenance data; do not treat external/banker price targets as reliable.")
        return "usable_but_discount_confidence", "moderate", cautions
    if status == "aggregate_only":
        cautions.append("Analyst target evidence is aggregate-only; discount external target confirmation.")
        return "usable_but_discount_confidence", "moderate", cautions
    if status in {"thin", "concentrated"}:
        cautions.append("Independent target support is present but below clean confidence policy.")
        return "usable_but_discount_confidence", "moderate", cautions
    if status == "high_confidence" and technical.get("technical_status") == "clean":
        return "target_supported", "high", cautions
    if status == "usable":
        return "target_supported", "moderate", cautions
    return "usable_but_discount_confidence", "moderate", cautions


def build_target_quality_context(
    tickers: list[str] | str | None = None,
    *,
    candidate_rows: list[dict[str, Any]] | None = None,
    report_dir: str | Path = REPORTS,
    knowledge_db: str | Path = KB,
    config_path: str | Path = CONFIG,
    now: datetime | None = None,
) -> dict[str, Any]:
    report_dir = Path(report_dir)
    knowledge_db = Path(knowledge_db)
    config_path = Path(config_path)
    now = now or datetime.now(timezone.utc)
    policy = _read_policy(config_path)
    supplied = _as_tickers(tickers)
    candidates = [dict(r) for r in (candidate_rows or _load_candidates(report_dir))]
    if supplied:
        have = {_ticker(c.get("ticker") or c.get("symbol")) for c in candidates}
        for symbol in supplied:
            if symbol not in have:
                candidates.append({"ticker": symbol, "_source_report": "supplied_ticker"})
        candidates = [c for c in candidates if _ticker(c.get("ticker") or c.get("symbol")) in supplied]

    ordered_tickers = []
    for row in candidates:
        symbol = _ticker(row.get("ticker") or row.get("symbol"))
        if symbol and symbol not in ordered_tickers:
            ordered_tickers.append(symbol)

    provenance = build_provenance_scorecard(
        candidate_tickers=ordered_tickers,
        knowledge_db=knowledge_db,
        report_dir=report_dir,
        config_path=config_path,
        now=now,
    )
    provenance_by = {str(r.get("ticker", "")).upper(): r for r in provenance.get("rows") or []}
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        symbol = _ticker(candidate.get("ticker") or candidate.get("symbol"))
        if not symbol:
            continue
        tech = _technical_context(candidate, policy)
        prov = provenance_by.get(symbol, {"status": "missing", "cautions": ["No analyst-target rows found for candidate."]})
        verdict, ceiling, cautions = _row_verdict(tech, prov)
        rows.append({
            "ticker": symbol,
            "source_report": candidate.get("_source_report"),
            "verdict": verdict,
            "confidence_ceiling": ceiling,
            **tech,
            "analyst_provenance_status": prov.get("status"),
            "analyst_provenance_verdict": prov.get("verdict"),
            "recent_independent_rows": prov.get("recent_independent_rows", 0),
            "unique_independent_brokers": prov.get("unique_independent_brokers", 0),
            "source_concentration_pct": prov.get("source_concentration_pct"),
            "analyst_target_median": prov.get("target_median"),
            "independent_analyst_target_median": prov.get("independent_target_median"),
            "target_dispersion_pct": prov.get("target_dispersion_pct"),
            "cautions": list(dict.fromkeys(cautions)),
        })

    total = len(rows)
    supported = sum(1 for r in rows if r["verdict"] == "target_supported")
    discounted = sum(1 for r in rows if r["verdict"] == "usable_but_discount_confidence")
    untrusted = sum(1 for r in rows if r["verdict"] == "target_untrusted")
    blockers: list[str] = []
    if total == 0:
        blockers.append("no target candidates found")
    if provenance.get("blockers"):
        blockers.extend(f"analyst_provenance: {b}" for b in provenance.get("blockers", []))
    if untrusted:
        blockers.append(f"{untrusted} candidate target plan(s) fail technical target checks")

    if supported == total and total > 0:
        verdict = "target_supported"
        confidence_ceiling = "high" if all(r["confidence_ceiling"] == "high" for r in rows) else "moderate"
    elif discounted or supported:
        verdict = "usable_but_discount_confidence"
        confidence_ceiling = "moderate"
    else:
        verdict = "target_untrusted"
        confidence_ceiling = "low"

    return {
        "available": True,
        "mode": "target_quality_context_v1",
        "asof": now.isoformat(),
        "verdict": verdict,
        "confidence_ceiling": confidence_ceiling,
        "candidate_count": total,
        "coverage": {
            "target_supported_pct": round(100.0 * supported / total, 1) if total else 0.0,
            "discounted_confidence_pct": round(100.0 * discounted / total, 1) if total else 0.0,
            "target_untrusted_pct": round(100.0 * untrusted / total, 1) if total else 0.0,
        },
        "rows": rows,
        "analyst_target_provenance": {
            "verdict": provenance.get("verdict"),
            "confidence_ceiling": provenance.get("confidence_ceiling"),
            "coverage": provenance.get("coverage"),
            "blockers": provenance.get("blockers"),
        },
        "blockers": blockers,
        "required_next_actions": [
            "Keep technical targets tied to explicit entry, stop, and reward/risk.",
            "Ingest independent broker/analyst target provenance before external targets can raise confidence.",
            "Treat missing or aggregate-only analyst targets as confidence discounts, not bullish confirmation.",
        ],
        "disclaimer": DISCLAIMER,
    }


def render_md(report: dict[str, Any]) -> str:
    cov = report.get("coverage") or {}
    lines = [
        f"# Target Quality - {report.get('verdict')}",
        "",
        f"Generated: {report.get('asof')}",
        f"Confidence ceiling: {report.get('confidence_ceiling')}",
        f"Candidates: {report.get('candidate_count')}",
        "",
        "## Coverage",
        f"- Target supported: {cov.get('target_supported_pct')}%",
        f"- Discounted confidence: {cov.get('discounted_confidence_pct')}%",
        f"- Target untrusted: {cov.get('target_untrusted_pct')}%",
        "",
        "## Rows",
        "| Ticker | Verdict | Ceiling | R:R | Upside | Provenance | Brokers | Cautions |",
        "|---|---|---|---:|---:|---|---:|---|",
    ]
    for row in report.get("rows") or []:
        lines.append(
            f"| {row.get('ticker')} | {row.get('verdict')} | {row.get('confidence_ceiling')} | "
            f"{row.get('reward_risk')} | {row.get('modeled_upside_pct')} | "
            f"{row.get('analyst_provenance_status')} | {row.get('unique_independent_brokers')} | "
            f"{'; '.join(row.get('cautions') or []) or '-'} |"
        )
    lines += ["", "## Blockers"]
    blockers = report.get("blockers") or []
    lines.extend(f"- {b}" for b in blockers) if blockers else lines.append("- none")
    lines += ["", "## Required Next Actions"]
    lines.extend(f"- {a}" for a in report.get("required_next_actions", []))
    lines += ["", report.get("disclaimer", DISCLAIMER)]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any] | None = None) -> dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or build_target_quality_context()
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render_md(report))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build target quality context")
    ap.add_argument("--tickers", nargs="*")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = build_target_quality_context(tickers=args.tickers or None)
    if args.write:
        write_reports(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(
            f"Target quality: verdict={report.get('verdict')} "
            f"candidates={report.get('candidate_count')} ceiling={report.get('confidence_ceiling')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
