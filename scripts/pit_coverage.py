#!/usr/bin/env python3
"""Point-in-time and survivorship coverage scorecard.

This is an audit module, not an alpha module. It measures whether the current
research universe can support point-in-time/survivorship-safe claims, and it
keeps candidate traceability separate from full PIT closure.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from paths import DATA_DIR, KNOWLEDGE_DB, PRICES_DB, REPORTS_DIR

REPORTS = REPORTS_DIR
PRICES = PRICES_DB
KB = KNOWLEDGE_DB
OUT_JSON = REPORTS / "pit-coverage.json"
OUT_MD = REPORTS / "pit-coverage.md"

PIT_COLUMNS = {"active", "delisted_at", "valid_from", "valid_to", "as_of", "source"}
DISCLAIMER = (
    "PIT coverage is an evidence audit only. Candidate price traceability does "
    "not close survivorship bias unless the universe is delisted-inclusive and "
    "point-in-time."
)


def _connect(path: Path, *, read_only: bool = True):
    import duckdb

    return duckdb.connect(str(path), read_only=read_only)


def _tables(path: Path) -> set[str]:
    if not path.exists():
        return set()
    con = _connect(path)
    try:
        return {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
    finally:
        con.close()


def _columns(path: Path, table: str) -> set[str]:
    if not path.exists():
        return set()
    con = _connect(path)
    try:
        return {str(r[0]) for r in con.execute(f"DESCRIBE {table}").fetchall()}
    except Exception:
        return set()
    finally:
        con.close()


def _count(path: Path, sql: str, params: list[Any] | None = None) -> int:
    if not path.exists():
        return 0
    con = _connect(path)
    try:
        return int(con.execute(sql, params or []).fetchone()[0] or 0)
    except Exception:
        return 0
    finally:
        con.close()


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _candidate_tickers(report_dir: Path = REPORTS) -> list[str]:
    out: list[str] = []

    def add(symbol: Any) -> None:
        s = str(symbol or "").upper().strip()
        if s and s not in out:
            out.append(s)

    for name in ("recommendations.json", "smart-recommendations.json", "super-smart-recommendations.json"):
        data = _json(report_dir / name, {})
        for row in data.get("picks") or []:
            add(row.get("ticker") or row.get("symbol"))
        for symbol in data.get("strict_current_picks") or []:
            add(symbol)
        for row in data.get("watch_list") or []:
            add(row.get("ticker") or row.get("symbol"))

    skill = _json(report_dir / "paper-skill-lab-latest.json", {})
    for symbol in skill.get("ensemble_top3") or []:
        add(symbol)

    quick = _json(report_dir / "quick-3stock-backtest-latest.json", {})
    symbols = (
        (quick.get("best_detail") or {}).get("current_top3_by_same_score_as_of_latest_date")
        or ((quick.get("best") or {}).get("current_top3_by_same_score_as_of_latest_date"))
        or []
    )
    for symbol in symbols:
        add(symbol)
    return out


def _candidate_traceability(tickers: list[str]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ticker in tickers:
        price_rows = _count(PRICES, "SELECT COUNT(*) FROM prices WHERE ticker = ?", [ticker])
        universe_rows = _count(PRICES, "SELECT COUNT(*) FROM universe WHERE ticker = ?", [ticker])
        rows.append({
            "ticker": ticker,
            "price_rows": price_rows,
            "universe_rows": universe_rows,
            "price_traceable": price_rows > 0,
            "universe_traceable": universe_rows > 0,
        })
    total = len(rows)
    traceable = sum(1 for r in rows if r["price_traceable"] and r["universe_traceable"])
    pct = round(100.0 * traceable / total, 2) if total else 0.0
    if pct >= 95:
        status = "excellent"
    elif pct >= 75:
        status = "partial"
    elif total:
        status = "poor"
    else:
        status = "no_candidates"
    return {
        "candidate_count": total,
        "candidate_traceable": traceable,
        "candidate_traceable_pct": pct,
        "candidate_coverage_status": status,
        "candidate_rows": rows,
    }


def compute_pit_coverage(candidate_tickers: list[str] | None = None) -> dict[str, Any]:
    price_tables = _tables(PRICES)
    knowledge_tables = _tables(KB)
    universe_cols = _columns(PRICES, "universe") if "universe" in price_tables else set()
    has_prices = "prices" in price_tables and _count(PRICES, "SELECT COUNT(*) FROM prices") > 0
    universe_rows = _count(PRICES, "SELECT COUNT(*) FROM universe") if "universe" in price_tables else 0
    has_pit_columns = bool(universe_cols & PIT_COLUMNS)
    if "active" in universe_cols and "delisted_at" in universe_cols:
        delisted_rows = _count(PRICES, "SELECT COUNT(*) FROM universe WHERE active = false OR delisted_at IS NOT NULL")
    elif "active" in universe_cols:
        delisted_rows = _count(PRICES, "SELECT COUNT(*) FROM universe WHERE active = false")
    elif "delisted_at" in universe_cols:
        delisted_rows = _count(PRICES, "SELECT COUNT(*) FROM universe WHERE delisted_at IS NOT NULL")
    else:
        delisted_rows = 0
    delisted_pct = round(100.0 * delisted_rows / universe_rows, 2) if universe_rows else 0.0

    inactive_reference = _count(KB, "SELECT COUNT(*) FROM polygon_tickers WHERE active = false") if "polygon_tickers" in knowledge_tables else 0
    splits = _count(KB, "SELECT COUNT(*) FROM polygon_splits") if "polygon_splits" in knowledge_tables else 0
    dividends = _count(KB, "SELECT COUNT(*) FROM polygon_dividends") if "polygon_dividends" in knowledge_tables else 0
    corporate_action_rows = splits + dividends

    tickers = candidate_tickers or _candidate_tickers(REPORTS)
    trace = _candidate_traceability(tickers)

    has_point_in_time_universe = has_prices and universe_rows > 0 and has_pit_columns and delisted_rows > 0
    has_vendor_pit_universe = has_point_in_time_universe
    corporate_actions_ok = corporate_action_rows > 0
    closed = (
        has_point_in_time_universe
        and corporate_actions_ok
        and trace["candidate_traceable_pct"] >= 95.0
    )
    if closed:
        status = "closed"
    elif has_point_in_time_universe or inactive_reference or corporate_action_rows:
        status = "partial_reference"
    else:
        status = "open"

    blockers: list[str] = []
    if not has_prices:
        blockers.append("price table missing or empty")
    if universe_rows <= 0:
        blockers.append("universe table missing or empty")
    if not has_pit_columns:
        blockers.append("universe lacks PIT/delisting columns")
    if delisted_rows <= 0:
        blockers.append("no delisted/inactive rows in PIT universe")
    if not corporate_actions_ok:
        blockers.append("corporate-action reference missing")
    if trace["candidate_traceable_pct"] < 95.0:
        blockers.append("candidate local price/universe traceability below 95%")

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "closed": closed,
        "has_prices": has_prices,
        "has_universe": universe_rows > 0,
        "universe_rows": universe_rows,
        "universe_columns": sorted(universe_cols),
        "has_point_in_time_universe": has_point_in_time_universe,
        "has_vendor_pit_universe": has_vendor_pit_universe,
        "delisted_rows": delisted_rows,
        "delisted_included_pct": delisted_pct,
        "polygon_inactive_reference_rows": inactive_reference,
        "corporate_action_rows": corporate_action_rows,
        "splits_rows": splits,
        "dividends_rows": dividends,
        **trace,
        "blockers": blockers,
        "required_next_actions": [
            "Import or build a delisted-inclusive point-in-time universe with active/delisted timestamps.",
            "Bind every price row to the universe state valid at that historical date.",
            "Collect split/dividend/symbol-change corporate actions for every traded candidate.",
            "Keep candidate traceability >=95% before any 9/10 research-quality claim.",
        ],
        "methodology_caveat": DISCLAIMER,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        f"# PIT Coverage - {report.get('status')}",
        "",
        f"Generated: {report.get('asof')}",
        f"Closed: {report.get('closed')}",
        f"Universe rows: {report.get('universe_rows')}",
        f"Delisted rows: {report.get('delisted_rows')} ({report.get('delisted_included_pct')}%)",
        f"Candidate traceability: {report.get('candidate_traceable_pct')}% ({report.get('candidate_coverage_status')})",
        f"Corporate action rows: {report.get('corporate_action_rows')}",
        "",
        "## Blockers",
    ]
    lines.extend([f"- {b}" for b in report.get("blockers", [])] or ["- none"])
    lines += ["", "## Required Next Actions"]
    lines.extend(f"- {a}" for a in report.get("required_next_actions", []))
    lines += ["", report.get("methodology_caveat", DISCLAIMER)]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any] | None = None) -> dict[str, str]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or compute_pit_coverage()
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render_md(report))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PIT/survivorship coverage audit")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = compute_pit_coverage()
    write_reports(report)
    print(json.dumps(report, indent=2, default=str) if args.json else render_md(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
