#!/usr/bin/env python3
"""Analyst-target provenance and independence scorecard.

This module is an audit layer, not a price-target engine. It checks whether
locally stored analyst target rows contain enough broker/analyst/date/source
provenance to be used as research context. Provider aggregates are explicitly
discounted and never counted as independent analyst evidence.
"""
from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import duckdb
import yaml

from paths import CONFIG_DIR, KNOWLEDGE_DB, REPORTS_DIR

KB = KNOWLEDGE_DB
REPORTS = REPORTS_DIR
CONFIG = CONFIG_DIR / "target_quality.yaml"
OUT_JSON = REPORTS / "analyst-target-provenance-latest.json"
OUT_MD = REPORTS / "analyst-target-provenance-latest.md"

DISCLAIMER = (
    "Analyst targets are research context only, not predictions or trade "
    "instructions. Provider aggregates are discounted and do not satisfy "
    "independent broker/analyst provenance."
)

DEFAULT_POLICY = {
    "freshness": {"max_analyst_target_age_days": 120, "stale_after_days": 60},
    "analyst_target_risk": {
        "min_independent_brokers_for_confidence": 5,
        "min_independent_brokers_for_high_confidence": 8,
        "max_single_source_weight_pct": 35,
    },
}

AGGREGATE_TERMS = (
    "aggregate",
    "consensus",
    "median",
    "provider",
    "finnhub",
    "tipranks",
    "marketbeat",
    "refinitiv",
    "factset",
)

INDEPENDENT_PROVENANCE = {
    "broker_analyst",
    "independent_broker",
    "broker_research",
    "primary_broker_source",
}


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


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


def _pct(num: float, den: float) -> float:
    return round(100.0 * float(num) / float(den), 1) if den else 0.0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        f = float(value)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).strip().replace("Z", "+00:00")
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            try:
                dt = datetime.strptime(text[:10], "%Y-%m-%d")
            except Exception:
                return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _age_days(value: Any, now: datetime) -> int | None:
    dt = _as_datetime(value)
    if dt is None:
        return None
    ref = now.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0, (ref.date() - dt.date()).days)


def _normal_ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def _add_ticker(out: list[str], value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        for part in value.replace(",", " ").split():
            t = _normal_ticker(part)
            if t and not t.startswith("^") and "=" not in t and t not in out:
                out.append(t)
        return
    if isinstance(value, dict):
        _add_ticker(out, value.get("ticker") or value.get("symbol"))
        return
    if isinstance(value, (list, tuple)):
        for item in value:
            _add_ticker(out, item)


def infer_candidate_tickers(limit: int = 40, report_dir: Path = REPORTS) -> list[str]:
    tickers: list[str] = []
    for name in (
        "super-smart-recommendations.json",
        "recommendations.json",
        "smart-recommendations.json",
        "ai-pattern-recommendations-latest.json",
    ):
        data = _read_json(report_dir / name, {})
        _add_ticker(tickers, data.get("strict_current_picks"))
        _add_ticker(tickers, data.get("picks"))
        _add_ticker(tickers, data.get("watch_list"))
        _add_ticker(tickers, data.get("recommendations"))

    skill = _read_json(report_dir / "paper-skill-lab-latest.json", {})
    _add_ticker(tickers, skill.get("ensemble_top3"))

    quick = _read_json(report_dir / "quick-3stock-backtest-latest.json", {})
    _add_ticker(
        tickers,
        (quick.get("best_detail") or {}).get("current_top3_by_same_score_as_of_latest_date")
        or (quick.get("best") or {}).get("current_top3_by_same_score_as_of_latest_date"),
    )

    if not tickers:
        rank = _read_json(report_dir / "ai-swing-hold-rank.json", {})
        _add_ticker(tickers, rank.get("top") or rank.get("all"))
    return tickers[: int(limit)]


def _tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:
        return set()
    try:
        return {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()


def _columns(path: Path, table: str) -> set[str]:
    if not path.exists():
        return set()
    try:
        con = duckdb.connect(str(path), read_only=True)
    except Exception:
        return set()
    try:
        return {str(r[0]) for r in con.execute(f"DESCRIBE {table}").fetchall()}
    except Exception:
        return set()
    finally:
        con.close()


def _expr(cols: set[str], names: tuple[str, ...], alias: str, default: str = "NULL") -> str:
    for name in names:
        if name in cols:
            return f'"{name}" AS "{alias}"'
    return f"{default} AS \"{alias}\""


def _load_rows(db_path: Path, tickers: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    if not db_path.exists():
        return [], ["knowledge.duckdb missing"]
    if "analyst_targets" not in _tables(db_path):
        return [], ["analyst_targets table missing"]
    cols = _columns(db_path, "analyst_targets")
    if "ticker" not in cols:
        return [], ["analyst_targets.ticker column missing"]

    select = [
        '"ticker" AS "ticker"',
        _expr(cols, ("broker", "firm", "source_firm"), "broker", "''"),
        _expr(cols, ("analyst", "analyst_name"), "analyst", "''"),
        _expr(cols, ("rating", "recommendation"), "rating", "''"),
        _expr(cols, ("action", "rating_action"), "action", "''"),
        _expr(cols, ("target", "price_target", "target_price"), "target"),
        _expr(cols, ("date", "published_at", "target_date", "published_date"), "published_at"),
        _expr(cols, ("source_url", "url"), "source_url", "''"),
        _expr(cols, ("provider", "vendor"), "provider", "''"),
        _expr(cols, ("provenance_level", "provenance"), "provenance_level", "''"),
        _expr(cols, ("ingested_at", "fetched_at"), "ingested_at"),
    ]
    placeholders = ",".join(["?"] * len(tickers))
    where = f"WHERE upper(ticker) IN ({placeholders})" if tickers else ""
    sql = f"SELECT {', '.join(select)} FROM analyst_targets {where}"
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        names = [d[0] for d in con.execute(sql, tickers).description]
        return [dict(zip(names, row)) for row in con.fetchall()], []
    except Exception as exc:
        return [], [f"analyst_targets query failed: {exc}"]
    finally:
        con.close()


def _contains_aggregate_text(row: dict[str, Any]) -> bool:
    text = " ".join(
        str(row.get(k) or "").lower()
        for k in ("broker", "analyst", "provider", "provenance_level", "rating", "action")
    )
    return any(term in text for term in AGGREGATE_TERMS)


def _is_independent(row: dict[str, Any]) -> bool:
    provenance = str(row.get("provenance_level") or "").strip().lower()
    broker = str(row.get("broker") or "").strip()
    analyst = str(row.get("analyst") or "").strip()
    source_url = str(row.get("source_url") or "").strip()
    target = _safe_float(row.get("target"))

    if not target or target <= 0 or not source_url:
        return False
    if _contains_aggregate_text(row) and provenance not in INDEPENDENT_PROVENANCE:
        return False
    if provenance in INDEPENDENT_PROVENANCE and broker and analyst:
        return True
    return bool(broker and analyst and not _contains_aggregate_text(row))


def _row_summary(
    ticker: str,
    rows: list[dict[str, Any]],
    *,
    now: datetime,
    max_age_days: int,
    stale_after_days: int,
    min_brokers: int,
    min_high_brokers: int,
    max_source_weight_pct: float,
) -> dict[str, Any]:
    recent = []
    stale = []
    for row in rows:
        age = _age_days(row.get("published_at"), now)
        if age is not None and age <= max_age_days and (_safe_float(row.get("target")) or 0) > 0:
            recent.append(row)
        else:
            stale.append(row)

    independent = [r for r in recent if _is_independent(r)]
    aggregate = [r for r in recent if _contains_aggregate_text(r) and not _is_independent(r)]
    brokers = sorted({str(r.get("broker") or "").strip() for r in independent if str(r.get("broker") or "").strip()})
    analysts = sorted({str(r.get("analyst") or "").strip() for r in independent if str(r.get("analyst") or "").strip()})
    targets = sorted(t for t in (_safe_float(r.get("target")) for r in recent) if t is not None and t > 0)
    independent_targets = sorted(t for t in (_safe_float(r.get("target")) for r in independent) if t is not None and t > 0)
    broker_counts = Counter(str(r.get("broker") or "unknown").strip() or "unknown" for r in recent)
    concentration = _pct(max(broker_counts.values()) if broker_counts else 0, len(recent))
    latest_age = min((_age_days(r.get("published_at"), now) for r in recent), default=None)
    latest_independent_age = min((_age_days(r.get("published_at"), now) for r in independent), default=None)

    cautions: list[str] = []
    if not rows:
        status = "missing"
        verdict = "do_not_use"
        cautions.append("No analyst-target rows found for candidate.")
    elif not recent:
        status = "stale"
        verdict = "do_not_use"
        cautions.append(f"No target row is within the {max_age_days}-day freshness window.")
    elif not independent and aggregate:
        status = "aggregate_only"
        verdict = "discount"
        cautions.append("Only provider aggregate/consensus targets are present; do not count them as independent evidence.")
    elif len(brokers) < min_brokers:
        status = "thin"
        verdict = "discount"
        cautions.append(f"Independent broker count {len(brokers)} is below policy minimum {min_brokers}.")
    elif concentration > max_source_weight_pct:
        status = "concentrated"
        verdict = "discount"
        cautions.append(f"Single-source concentration {concentration}% exceeds policy cap {max_source_weight_pct}%.")
    elif len(brokers) >= min_high_brokers:
        status = "high_confidence"
        verdict = "strong_research_context"
    else:
        status = "usable"
        verdict = "usable_research"

    if latest_independent_age is not None and latest_independent_age > stale_after_days:
        cautions.append(f"Latest independent target is older than stale-after threshold ({stale_after_days} days).")

    median_target = round(float(median(targets)), 2) if targets else None
    min_target = round(float(min(targets)), 2) if targets else None
    max_target = round(float(max(targets)), 2) if targets else None
    dispersion_pct = None
    if median_target and min_target is not None and max_target is not None:
        dispersion_pct = round(100.0 * (max_target - min_target) / median_target, 2)

    independent_median = round(float(median(independent_targets)), 2) if independent_targets else None
    return {
        "ticker": ticker,
        "status": status,
        "verdict": verdict,
        "total_rows": len(rows),
        "recent_rows": len(recent),
        "stale_or_invalid_rows": len(stale),
        "recent_independent_rows": len(independent),
        "recent_aggregate_rows": len(aggregate),
        "unique_independent_brokers": len(brokers),
        "unique_independent_analysts": len(analysts),
        "latest_target_age_days": latest_age,
        "latest_independent_target_age_days": latest_independent_age,
        "source_concentration_pct": concentration,
        "target_min": min_target,
        "target_median": median_target,
        "target_max": max_target,
        "independent_target_median": independent_median,
        "target_dispersion_pct": dispersion_pct,
        "brokers": brokers[:20],
        "analysts": analysts[:20],
        "cautions": cautions,
    }


def build_scorecard(
    candidate_tickers: list[str] | str | None = None,
    *,
    tickers: list[str] | str | None = None,
    knowledge_db: str | Path = KB,
    report_dir: str | Path = REPORTS,
    config_path: str | Path = CONFIG,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a candidate-level analyst-target provenance scorecard."""
    now = now or datetime.now(timezone.utc)
    report_dir = Path(report_dir)
    knowledge_db = Path(knowledge_db)
    config_path = Path(config_path)
    raw_tickers = tickers if tickers is not None else candidate_tickers
    if isinstance(raw_tickers, str):
        candidate_list = []
        _add_ticker(candidate_list, raw_tickers)
    elif raw_tickers:
        candidate_list = []
        _add_ticker(candidate_list, raw_tickers)
    else:
        candidate_list = infer_candidate_tickers(report_dir=report_dir)
    candidate_list = list(dict.fromkeys(_normal_ticker(t) for t in candidate_list if _normal_ticker(t)))

    policy = _read_policy(config_path)
    freshness = policy.get("freshness") or {}
    risk = policy.get("analyst_target_risk") or {}
    max_age_days = int(freshness.get("max_analyst_target_age_days", 120))
    stale_after_days = int(freshness.get("stale_after_days", 60))
    min_brokers = int(risk.get("min_independent_brokers_for_confidence", 5))
    min_high_brokers = int(risk.get("min_independent_brokers_for_high_confidence", 8))
    max_source_weight_pct = float(risk.get("max_single_source_weight_pct", 35))

    rows, load_blockers = _load_rows(knowledge_db, candidate_list)
    by_ticker: dict[str, list[dict[str, Any]]] = {t: [] for t in candidate_list}
    for row in rows:
        ticker = _normal_ticker(row.get("ticker"))
        if ticker in by_ticker:
            by_ticker[ticker].append(row)

    summaries = [
        _row_summary(
            ticker,
            by_ticker.get(ticker, []),
            now=now,
            max_age_days=max_age_days,
            stale_after_days=stale_after_days,
            min_brokers=min_brokers,
            min_high_brokers=min_high_brokers,
            max_source_weight_pct=max_source_weight_pct,
        )
        for ticker in candidate_list
    ]

    n = len(candidate_list)
    with_recent = sum(1 for row in summaries if row["recent_rows"] > 0)
    with_independent = sum(1 for row in summaries if row["recent_independent_rows"] > 0)
    usable = sum(1 for row in summaries if row["status"] in {"usable", "high_confidence"})
    high = sum(1 for row in summaries if row["status"] == "high_confidence")
    aggregate_only = sum(1 for row in summaries if row["status"] == "aggregate_only")
    missing = sum(1 for row in summaries if row["status"] in {"missing", "stale"})

    blockers = list(load_blockers)
    if not candidate_list:
        blockers.append("no candidate tickers inferred or supplied")
    if n and with_independent == 0:
        blockers.append("no candidate has recent independent broker/analyst target provenance")
    if n and usable == 0:
        blockers.append("no candidate satisfies independent-broker count and concentration policy")

    if not candidate_list or load_blockers:
        verdict = "missing"
        confidence_ceiling = "low"
    elif with_independent == 0:
        verdict = "weak"
        confidence_ceiling = "low"
    elif usable / n >= 0.8:
        verdict = "usable"
        confidence_ceiling = "high" if high / n >= 0.5 else "moderate"
    else:
        verdict = "partial"
        confidence_ceiling = "moderate" if usable else "low"

    return {
        "available": True,
        "mode": "analyst_target_provenance_scorecard_v1",
        "asof_utc": now.isoformat(),
        "verdict": verdict,
        "confidence_ceiling": confidence_ceiling,
        "candidate_count": n,
        "policy": {
            "max_analyst_target_age_days": max_age_days,
            "stale_after_days": stale_after_days,
            "min_independent_brokers_for_confidence": min_brokers,
            "min_independent_brokers_for_high_confidence": min_high_brokers,
            "max_single_source_weight_pct": max_source_weight_pct,
        },
        "coverage": {
            "tickers_with_any_recent_pct": _pct(with_recent, n),
            "independent_provenance_pct": _pct(with_independent, n),
            "usable_research_context_pct": _pct(usable, n),
            "high_confidence_context_pct": _pct(high, n),
            "aggregate_only_pct": _pct(aggregate_only, n),
            "missing_or_stale_pct": _pct(missing, n),
        },
        "rows": summaries,
        "blockers": blockers,
        "required_next_actions": [
            "Ingest lawful broker/analyst-level target rows with ticker, broker, analyst, target, date, source_url, provider, and provenance_level.",
            "Keep provider aggregates tagged as provider_aggregate so they remain discounted.",
            "Require multiple independent broker sources before analyst targets can raise research confidence.",
        ],
        "report_paths": {
            "json": str(OUT_JSON),
            "markdown": str(OUT_MD),
        },
        "disclaimer": DISCLAIMER,
    }


def render_md(report: dict[str, Any]) -> str:
    cov = report.get("coverage") or {}
    lines = [
        f"# Analyst Target Provenance - {report.get('verdict')}",
        "",
        f"Generated: {report.get('asof_utc')}",
        f"Confidence ceiling: {report.get('confidence_ceiling')}",
        f"Candidates: {report.get('candidate_count')}",
        "",
        "## Coverage",
        f"- Any recent target rows: {cov.get('tickers_with_any_recent_pct')}%",
        f"- Independent broker/analyst provenance: {cov.get('independent_provenance_pct')}%",
        f"- Usable research context: {cov.get('usable_research_context_pct')}%",
        f"- High-confidence context: {cov.get('high_confidence_context_pct')}%",
        f"- Aggregate-only targets: {cov.get('aggregate_only_pct')}%",
        f"- Missing/stale targets: {cov.get('missing_or_stale_pct')}%",
        "",
        "## Candidate Rows",
        "| Ticker | Status | Verdict | Recent | Independent | Aggregate | Brokers | Concentration | Median Target | Cautions |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in report.get("rows") or []:
        lines.append(
            f"| {row.get('ticker')} | {row.get('status')} | {row.get('verdict')} | "
            f"{row.get('recent_rows')} | {row.get('recent_independent_rows')} | "
            f"{row.get('recent_aggregate_rows')} | {row.get('unique_independent_brokers')} | "
            f"{row.get('source_concentration_pct')} | {row.get('target_median')} | "
            f"{'; '.join(row.get('cautions') or []) or '-'} |"
        )
    lines += ["", "## Blockers"]
    blockers = report.get("blockers") or []
    if blockers:
        lines.extend(f"- {b}" for b in blockers)
    else:
        lines.append("- none")
    lines += ["", "## Required Next Actions"]
    lines.extend(f"- {a}" for a in report.get("required_next_actions", []))
    lines += ["", report.get("disclaimer", DISCLAIMER)]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any] | None = None) -> dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or build_scorecard()
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render_md(report))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build analyst target provenance scorecard")
    ap.add_argument("--tickers", nargs="*", help="Optional ticker list; defaults to current candidates")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args(argv)
    report = build_scorecard(candidate_tickers=args.tickers or None)
    if args.write:
        write_reports(report)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        cov = report.get("coverage") or {}
        print(
            "Analyst target provenance: "
            f"verdict={report.get('verdict')} candidates={report.get('candidate_count')} "
            f"independent={cov.get('independent_provenance_pct')}% usable={cov.get('usable_research_context_pct')}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
