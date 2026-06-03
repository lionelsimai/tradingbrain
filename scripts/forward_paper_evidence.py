#!/usr/bin/env python3
"""Forward forecast evidence ledger.

This module records research-only forecast observations from the recommender
reports, then resolves them later when future price bars exist. It deliberately
does not submit orders, call broker adapters, or treat replay/backtest evidence
as paper fills. Its job is to turn today's proposals into auditable 1D/5D/20D
forward evidence without fabricating time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from paths import KNOWLEDGE_DB, PRICES_DB, REPORTS_DIR


KB = KNOWLEDGE_DB
PRICES = PRICES_DB
REPORTS = REPORTS_DIR
HORIZONS = (1, 5, 20)
DEFAULT_BENCHMARK = "SPY"
DEFAULT_SLIPPAGE_BPS = 5.0
EVIDENCE_JSON = "forward-paper-evidence.json"
HORIZON_JSON = "forward-paper-horizon-scorecard-latest.json"
HORIZON_MD = "forward-paper-horizon-scorecard-latest.md"

DISCLAIMER = (
    "Research-only forward observation ledger. Rows are not broker fills, not "
    "live trades, and not authorization to trade."
)


@dataclass(frozen=True)
class CandidateObservation:
    signal_date: date
    ticker: str
    strategy: str
    setup: str
    direction: str
    entry: float
    stop: float
    target: float | None
    benchmark: str
    source_report: str
    regime: str
    confidence: float | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _write_json(name: str, payload: dict[str, Any]) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / name
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str))
    return path


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
        if not math.isfinite(out):
            return None
        return out
    except Exception:
        return None


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if value:
        text = str(value).strip()
        for sep in ("T", " "):
            if sep in text:
                text = text.split(sep, 1)[0]
                break
        try:
            return date.fromisoformat(text)
        except Exception:
            pass
    return datetime.now(timezone.utc).date()


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _pct(numerator: int, denominator: int) -> float | None:
    return round(100.0 * numerator / denominator, 2) if denominator else None


def _observation_id(candidate: CandidateObservation, horizon_days: int) -> str:
    raw = "|".join(
        [
            candidate.signal_date.isoformat(),
            candidate.ticker.upper(),
            candidate.strategy,
            candidate.setup,
            str(horizon_days),
            f"{candidate.entry:.8f}",
            candidate.source_report,
        ]
    )
    return "fpo_" + hashlib.sha256(raw.encode()).hexdigest()[:20]


def _connect(read_only: bool = False):
    import duckdb

    if not read_only:
        KB.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(KB), read_only=read_only)


def _ensure_schema(con) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS forward_paper_observations (
            observation_id VARCHAR PRIMARY KEY,
            created_at TIMESTAMP,
            signal_date DATE,
            ticker VARCHAR,
            strategy VARCHAR,
            setup VARCHAR,
            horizon_days INTEGER,
            direction VARCHAR,
            entry DOUBLE,
            stop DOUBLE,
            target DOUBLE,
            benchmark VARCHAR,
            source_report VARCHAR,
            evidence_source VARCHAR,
            regime VARCHAR,
            confidence DOUBLE,
            status VARCHAR,
            resolved_at TIMESTAMP,
            exit_date DATE,
            exit_price DOUBLE,
            return_pct DOUBLE,
            realized_R DOUBLE,
            benchmark_return_pct DOUBLE,
            excess_return_pct DOUBLE,
            excess_return_R DOUBLE,
            slippage_adjusted_return_pct DOUBLE,
            slippage_adjusted_return_R DOUBLE,
            max_drawdown_pct DOUBLE,
            resolution_note VARCHAR
        )
        """
    )


def _table_exists(con, table_name: str) -> bool:
    try:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        return table_name in tables
    except Exception:
        return False


def _entry_from_candidate(row: dict[str, Any]) -> float | None:
    entry = _float(row.get("entry"))
    if entry is not None:
        return entry
    zone = row.get("entry_zone")
    if isinstance(zone, dict):
        low = _float(zone.get("low"))
        high = _float(zone.get("high"))
        if low is not None and high is not None:
            return round((low + high) / 2.0, 4)
    source = row.get("source_candidate")
    if isinstance(source, dict):
        return _float(source.get("last_close")) or _float(source.get("entry"))
    return _float(row.get("last_close")) or _float(row.get("price"))


def _stop_from_candidate(row: dict[str, Any]) -> float | None:
    source = row.get("source_candidate") if isinstance(row.get("source_candidate"), dict) else {}
    return (
        _float(row.get("stop_loss"))
        or _float(row.get("stop"))
        or _float(row.get("invalidation_price"))
        or _float(source.get("stop_loss"))
        or _float(source.get("stop"))
    )


def _target_from_candidate(row: dict[str, Any]) -> float | None:
    for key in ("target", "take_profit", "t1"):
        value = _float(row.get(key))
        if value is not None:
            return value
    targets = row.get("targets")
    if isinstance(targets, list) and targets:
        first = targets[0]
        if isinstance(first, dict):
            return _float(first.get("level")) or _float(first.get("price"))
        return _float(first)
    source = row.get("source_candidate")
    if isinstance(source, dict):
        return _float(source.get("target")) or _float(source.get("t1"))
    return None


def _confidence_from_candidate(row: dict[str, Any]) -> float | None:
    for key in ("confidence", "conviction_score", "recommender_score", "score"):
        value = _float(row.get(key))
        if value is None:
            continue
        return round(value / 100.0, 4) if value > 1.0 else round(value, 4)
    return None


def _iter_report_candidates(report: dict[str, Any], source_name: str, top: int) -> list[CandidateObservation]:
    rows: list[dict[str, Any]] = []
    for key in ("picks", "strict_current_picks", "recommendations", "candidates", "buys"):
        value = report.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                rows.append(item)
            elif isinstance(item, str):
                rows.append({"ticker": item, "setup": "STRICT_CURRENT_PICK"})
    out: list[CandidateObservation] = []
    signal_date = _parse_date(report.get("asof") or report.get("latest_price_date"))
    regime = str(
        (report.get("regime") or {}).get("label")
        if isinstance(report.get("regime"), dict)
        else report.get("regime")
        or (report.get("macro_context") or {}).get("stance")
        or "unknown"
    )
    for row in rows:
        if len(out) >= top:
            break
        ticker = str(row.get("ticker") or row.get("symbol") or "").upper().strip()
        if not ticker:
            continue
        entry = _entry_from_candidate(row)
        stop = _stop_from_candidate(row)
        if entry is None or stop is None or entry <= 0 or stop <= 0 or entry <= stop:
            continue
        strategy = str(row.get("strategy") or row.get("setup") or row.get("action_label") or "FORECAST").strip()
        setup = str(row.get("setup") or row.get("action_label") or strategy).strip()
        out.append(
            CandidateObservation(
                signal_date=signal_date,
                ticker=ticker,
                strategy=strategy,
                setup=setup,
                direction=str(row.get("direction") or "long").lower(),
                entry=float(entry),
                stop=float(stop),
                target=_target_from_candidate(row),
                benchmark=str(row.get("benchmark") or DEFAULT_BENCHMARK).upper(),
                source_report=source_name,
                regime=regime,
                confidence=_confidence_from_candidate(row),
            )
        )
    return out


def _load_latest_candidates(top: int = 20, refresh: bool = False) -> tuple[list[CandidateObservation], list[str]]:
    reports: list[tuple[str, Path]] = [
        ("super-smart-recommendations.json", REPORTS / "super-smart-recommendations.json"),
        ("forecast-recommendations-latest.json", REPORTS / "forecast-recommendations-latest.json"),
        ("recommendations.json", REPORTS / "recommendations.json"),
        ("forecast-smart-recommendations-latest.json", REPORTS / "forecast-smart-recommendations-latest.json"),
        ("smart-recommendations.json", REPORTS / "smart-recommendations.json"),
    ]
    if refresh and not reports[0][1].exists():
        try:
            from scripts.super_smart_recommender import build_super_smart_recommendations

            build_super_smart_recommendations(top=max(top, 20), refresh=False)
        except Exception:
            pass
    tried: list[str] = []
    for source_name, path in reports:
        tried.append(source_name)
        report = _json(path, {})
        candidates = _iter_report_candidates(report, source_name, top)
        if candidates:
            return candidates, tried
    return [], tried


def log_latest_super_smart(top: int = 20, refresh: bool = False) -> dict[str, Any]:
    """Append latest recommender candidates as pending forward observations.

    The write is idempotent across horizons and source reports. It records
    forecasts only; no broker path is imported or invoked.
    """
    candidates, tried_reports = _load_latest_candidates(top=top, refresh=refresh)
    inserted = 0
    duplicates = 0
    skipped = max(0, top - len(candidates))
    try:
        con = _connect(read_only=False)
    except Exception as exc:
        out = {
            "asof": _now(),
            "inserted_observations": 0,
            "duplicate_observations": 0,
            "skipped_candidates": skipped,
            "candidate_count": len(candidates),
            "horizons": list(HORIZONS),
            "reports_tried": tried_reports,
            "write_blocked": True,
            "error": f"forward evidence database is not writable: {exc}",
            "methodology_caveat": DISCLAIMER,
        }
        _write_json(EVIDENCE_JSON, out)
        return out
    try:
        _ensure_schema(con)
        for candidate in candidates:
            for horizon_days in HORIZONS:
                oid = _observation_id(candidate, horizon_days)
                exists = con.execute(
                    "SELECT 1 FROM forward_paper_observations WHERE observation_id=?",
                    [oid],
                ).fetchone()
                if exists:
                    duplicates += 1
                    continue
                con.execute(
                    """
                    INSERT INTO forward_paper_observations (
                        observation_id, created_at, signal_date, ticker, strategy,
                        setup, horizon_days, direction, entry, stop, target,
                        benchmark, source_report, evidence_source, regime,
                        confidence, status, resolution_note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                    """,
                    [
                        oid,
                        datetime.now(timezone.utc).replace(tzinfo=None),
                        candidate.signal_date,
                        candidate.ticker,
                        candidate.strategy,
                        candidate.setup,
                        horizon_days,
                        candidate.direction,
                        candidate.entry,
                        candidate.stop,
                        candidate.target,
                        candidate.benchmark,
                        candidate.source_report,
                        "research_forward_observation",
                        candidate.regime,
                        candidate.confidence,
                        "waiting for future market bars",
                    ],
                )
                inserted += 1
    finally:
        con.close()
    summary = summarize_forward_evidence(write=False)
    out = {
        "asof": _now(),
        "inserted_observations": inserted,
        "duplicate_observations": duplicates,
        "skipped_candidates": skipped,
        "candidate_count": len(candidates),
        "horizons": list(HORIZONS),
        "reports_tried": tried_reports,
        "summary": summary,
        "methodology_caveat": DISCLAIMER,
    }
    _write_json(EVIDENCE_JSON, out)
    return out


def summarize_forward_evidence(write: bool = True) -> dict[str, Any]:
    out = {
        "asof": _now(),
        "available": False,
        "total_observations": 0,
        "pending_observations": 0,
        "resolved_observations": 0,
        "invalid_observations": 0,
        "by_status": {},
        "by_horizon": [],
        "tickers": [],
        "regime_count": 0,
        "weeks_covered": 0,
        "decision_useful": False,
        "methodology_caveat": DISCLAIMER,
    }
    read_only = KB.exists()
    try:
        con = _connect(read_only=read_only)
    except Exception as exc:
        out["error"] = str(exc)
        if write:
            _write_json(EVIDENCE_JSON, out)
        return out
    try:
        if read_only and not _table_exists(con, "forward_paper_observations"):
            out["available"] = True
            if write:
                _write_json(EVIDENCE_JSON, out)
            return out
        if not read_only:
            _ensure_schema(con)
        statuses = con.execute(
            "SELECT COALESCE(status, 'unknown'), COUNT(*) FROM forward_paper_observations GROUP BY 1"
        ).fetchall()
        out["by_status"] = {str(row[0]): int(row[1]) for row in statuses}
        out["total_observations"] = int(sum(out["by_status"].values()))
        out["pending_observations"] = int(out["by_status"].get("pending", 0))
        out["resolved_observations"] = int(
            con.execute(
                "SELECT COUNT(*) FROM forward_paper_observations WHERE status='resolved' OR realized_R IS NOT NULL"
            ).fetchone()[0]
            or 0
        )
        out["invalid_observations"] = int(out["by_status"].get("invalid", 0))
        rows = con.execute(
            """
            SELECT horizon_days, COUNT(*),
                   SUM(CASE WHEN status='resolved' OR realized_R IS NOT NULL THEN 1 ELSE 0 END)
            FROM forward_paper_observations
            GROUP BY horizon_days
            ORDER BY horizon_days
            """
        ).fetchall()
        out["by_horizon"] = [
            {"horizon_days": int(r[0]), "observations": int(r[1]), "resolved": int(r[2] or 0)}
            for r in rows
        ]
        out["tickers"] = [
            r[0]
            for r in con.execute(
                "SELECT DISTINCT ticker FROM forward_paper_observations ORDER BY ticker"
            ).fetchall()
        ]
        out["regime_count"] = int(
            con.execute(
                "SELECT COUNT(DISTINCT regime) FROM forward_paper_observations WHERE regime IS NOT NULL"
            ).fetchone()[0]
            or 0
        )
        signal_dates = [
            _parse_date(r[0])
            for r in con.execute(
                "SELECT DISTINCT signal_date FROM forward_paper_observations WHERE signal_date IS NOT NULL"
            ).fetchall()
        ]
        out["weeks_covered"] = len({(d.isocalendar().year, d.isocalendar().week) for d in signal_dates})
        out["available"] = True
        out["decision_useful"] = out["resolved_observations"] >= 200
    finally:
        con.close()
    if write:
        _write_json(EVIDENCE_JSON, out)
    return out


def _price_rows(ticker: str, start_date: date) -> list[dict[str, Any]]:
    if not PRICES.exists():
        return []
    try:
        import duckdb

        con = duckdb.connect(str(PRICES), read_only=True)
        rows = con.execute(
            """
            SELECT date, open, high, low, close
            FROM prices
            WHERE ticker=? AND date>=?
            ORDER BY date
            """,
            [ticker.upper(), start_date],
        ).fetchall()
        con.close()
    except Exception:
        return []
    return [
        {
            "date": _parse_date(r[0]),
            "open": float(r[1]),
            "high": float(r[2]),
            "low": float(r[3]),
            "close": float(r[4]),
        }
        for r in rows
        if r[1] is not None and r[2] is not None and r[3] is not None and r[4] is not None
    ]


def _resolve_one(row: dict[str, Any], slippage_bps: float) -> dict[str, Any] | None:
    signal_date = _parse_date(row["signal_date"])
    horizon_days = int(row["horizon_days"])
    ticker_rows = _price_rows(str(row["ticker"]), signal_date)
    if len(ticker_rows) <= horizon_days:
        return None
    exit_bar = ticker_rows[horizon_days]
    entry = float(row["entry"])
    stop = float(row["stop"])
    risk = entry - stop
    if entry <= 0 or risk <= 0:
        return {
            "status": "invalid",
            "resolution_note": "invalid long-side entry/stop/risk geometry",
        }
    exit_price = float(exit_bar["close"])
    return_pct = (exit_price - entry) / entry * 100.0
    realized_r = (exit_price - entry) / risk
    lows = [float(r["low"]) for r in ticker_rows[: horizon_days + 1]]
    max_drawdown_pct = (min(lows) - entry) / entry * 100.0 if lows else None

    benchmark_return_pct = None
    excess_return_pct = None
    excess_return_r = None
    benchmark = str(row.get("benchmark") or DEFAULT_BENCHMARK).upper()
    bench_rows = _price_rows(benchmark, signal_date)
    if len(bench_rows) > horizon_days:
        bench_entry = float(bench_rows[0]["close"])
        bench_exit = float(bench_rows[horizon_days]["close"])
        if bench_entry > 0:
            benchmark_return_pct = (bench_exit - bench_entry) / bench_entry * 100.0
            excess_return_pct = return_pct - benchmark_return_pct
            excess_return_r = (excess_return_pct / 100.0 * entry) / risk

    slip = slippage_bps / 10000.0
    slipped_entry = entry * (1.0 + slip)
    slipped_exit = exit_price * (1.0 - slip)
    slippage_adjusted_return_pct = (slipped_exit - slipped_entry) / slipped_entry * 100.0
    slippage_adjusted_return_r = (slipped_exit - slipped_entry) / risk
    return {
        "status": "resolved",
        "resolved_at": datetime.now(timezone.utc).replace(tzinfo=None),
        "exit_date": exit_bar["date"],
        "exit_price": round(exit_price, 6),
        "return_pct": round(return_pct, 6),
        "realized_R": round(realized_r, 6),
        "benchmark_return_pct": round(benchmark_return_pct, 6) if benchmark_return_pct is not None else None,
        "excess_return_pct": round(excess_return_pct, 6) if excess_return_pct is not None else None,
        "excess_return_R": round(excess_return_r, 6) if excess_return_r is not None else None,
        "slippage_adjusted_return_pct": round(slippage_adjusted_return_pct, 6),
        "slippage_adjusted_return_R": round(slippage_adjusted_return_r, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6) if max_drawdown_pct is not None else None,
        "resolution_note": "resolved from first tradable bar on/after signal date to fixed horizon close",
    }


def resolve_pending_observations(slippage_bps: float = DEFAULT_SLIPPAGE_BPS) -> dict[str, Any]:
    try:
        con = _connect(read_only=False)
    except Exception as exc:
        return {
            "resolved_now": 0,
            "invalid_now": 0,
            "still_pending": None,
            "write_blocked": True,
            "error": f"forward evidence database is not writable: {exc}",
        }
    resolved = 0
    invalid = 0
    pending = 0
    try:
        _ensure_schema(con)
        cols = [
            "observation_id",
            "signal_date",
            "ticker",
            "horizon_days",
            "entry",
            "stop",
            "benchmark",
        ]
        rows = con.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM forward_paper_observations
            WHERE COALESCE(status, 'pending')='pending' AND realized_R IS NULL
            ORDER BY signal_date, ticker, horizon_days
            """
        ).fetchall()
        for raw in rows:
            row = dict(zip(cols, raw))
            outcome = _resolve_one(row, slippage_bps=slippage_bps)
            if outcome is None:
                pending += 1
                continue
            if outcome["status"] == "invalid":
                con.execute(
                    """
                    UPDATE forward_paper_observations
                    SET status='invalid', resolution_note=?
                    WHERE observation_id=?
                    """,
                    [outcome["resolution_note"], row["observation_id"]],
                )
                invalid += 1
                continue
            con.execute(
                """
                UPDATE forward_paper_observations
                SET status='resolved',
                    resolved_at=?,
                    exit_date=?,
                    exit_price=?,
                    return_pct=?,
                    realized_R=?,
                    benchmark_return_pct=?,
                    excess_return_pct=?,
                    excess_return_R=?,
                    slippage_adjusted_return_pct=?,
                    slippage_adjusted_return_R=?,
                    max_drawdown_pct=?,
                    resolution_note=?
                WHERE observation_id=?
                """,
                [
                    outcome["resolved_at"],
                    outcome["exit_date"],
                    outcome["exit_price"],
                    outcome["return_pct"],
                    outcome["realized_R"],
                    outcome["benchmark_return_pct"],
                    outcome["excess_return_pct"],
                    outcome["excess_return_R"],
                    outcome["slippage_adjusted_return_pct"],
                    outcome["slippage_adjusted_return_R"],
                    outcome["max_drawdown_pct"],
                    outcome["resolution_note"],
                    row["observation_id"],
                ],
            )
            resolved += 1
    finally:
        con.close()
    return {"resolved_now": resolved, "invalid_now": invalid, "still_pending": pending}


def _resolved_rows() -> list[dict[str, Any]]:
    read_only = KB.exists()
    con = _connect(read_only=read_only)
    try:
        if read_only and not _table_exists(con, "forward_paper_observations"):
            return []
        if not read_only:
            _ensure_schema(con)
        cols = [
            "horizon_days",
            "ticker",
            "signal_date",
            "regime",
            "realized_R",
            "return_pct",
            "benchmark_return_pct",
            "excess_return_pct",
            "excess_return_R",
            "slippage_adjusted_return_pct",
            "slippage_adjusted_return_R",
            "max_drawdown_pct",
        ]
        rows = con.execute(
            f"""
            SELECT {', '.join(cols)}
            FROM forward_paper_observations
            WHERE status='resolved' AND realized_R IS NOT NULL
            ORDER BY signal_date, ticker, horizon_days
            """
        ).fetchall()
        return [dict(zip(cols, row)) for row in rows]
    finally:
        con.close()


def _group_by_horizon(rows: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = {h: [] for h in HORIZONS}
    for row in rows:
        try:
            grouped.setdefault(int(row["horizon_days"]), []).append(row)
        except Exception:
            continue
    return grouped


def _scorecard(rows: list[dict[str, Any]], resolution: dict[str, Any]) -> dict[str, Any]:
    grouped = _group_by_horizon(rows)
    by_horizon: list[dict[str, Any]] = []
    bench_rows: list[dict[str, Any]] = []
    slip_rows: list[dict[str, Any]] = []
    for horizon_days in HORIZONS:
        group = grouped.get(horizon_days, [])
        rs = [float(r["realized_R"]) for r in group if r.get("realized_R") is not None]
        returns = [float(r["return_pct"]) for r in group if r.get("return_pct") is not None]
        dds = [float(r["max_drawdown_pct"]) for r in group if r.get("max_drawdown_pct") is not None]
        by_horizon.append(
            {
                "horizon_days": horizon_days,
                "n": len(rs),
                "hit_rate_pct": _pct(sum(1 for r in rs if r > 0), len(rs)),
                "avg_return_R": _mean(rs),
                "median_return_R": _median(rs),
                "avg_return_pct": _mean(returns),
                "avg_max_drawdown_pct": _mean(dds),
            }
        )
        excess_r = [float(r["excess_return_R"]) for r in group if r.get("excess_return_R") is not None]
        excess_pct = [float(r["excess_return_pct"]) for r in group if r.get("excess_return_pct") is not None]
        bench_rows.append(
            {
                "horizon_days": horizon_days,
                "n": len(excess_pct),
                "excess_hit_rate_pct": _pct(sum(1 for r in excess_pct if r > 0), len(excess_pct)),
                "avg_excess_return_pct": _mean(excess_pct),
                "avg_excess_return_R": _mean(excess_r),
            }
        )
        slip_r = [
            float(r["slippage_adjusted_return_R"])
            for r in group
            if r.get("slippage_adjusted_return_R") is not None
        ]
        slip_pct = [
            float(r["slippage_adjusted_return_pct"])
            for r in group
            if r.get("slippage_adjusted_return_pct") is not None
        ]
        slip_rows.append(
            {
                "horizon_days": horizon_days,
                "n": len(slip_r),
                "slippage_adjusted_hit_rate_pct": _pct(sum(1 for r in slip_r if r > 0), len(slip_r)),
                "avg_slippage_adjusted_return_pct": _mean(slip_pct),
                "avg_slippage_adjusted_return_R": _mean(slip_r),
            }
        )

    signal_dates = [_parse_date(r["signal_date"]) for r in rows if r.get("signal_date")]
    weeks = {(d.isocalendar().year, d.isocalendar().week) for d in signal_dates}
    regimes = {str(r.get("regime")) for r in rows if r.get("regime") not in (None, "", "None")}
    outcomes_total = len(rows)
    return {
        "asof": _now(),
        "status": "DECISION_USEFUL" if outcomes_total >= 200 else "INSUFFICIENT_FORWARD_EVIDENCE",
        "decision_useful": outcomes_total >= 200 and all((row.get("n") or 0) >= 50 for row in by_horizon),
        "outcomes_total": outcomes_total,
        "resolution": resolution,
        "by_horizon": by_horizon,
        "benchmark_adjusted_by_horizon": bench_rows,
        "benchmark_adjusted_evidence_present": any((row.get("n") or 0) > 0 for row in bench_rows),
        "slippage_adjusted_by_horizon": slip_rows,
        "regime_count": len(regimes),
        "weeks_covered": len(weeks),
        "required_next_evidence": [
            "Keep logging daily forecast observations before market action.",
            "Resolve after future bars exist; do not backfill today's recommendations with old data.",
            "Require 200+ resolved outcomes and at least 50 per 1D/5D/20D horizon before proof-gate promotion.",
        ],
        "methodology_caveat": DISCLAIMER,
    }


def _markdown(card: dict[str, Any]) -> str:
    lines = [
        f"# Forward Paper Horizon Scorecard - {card.get('status')}",
        "",
        f"Generated: {card.get('asof')}",
        f"Outcomes total: {card.get('outcomes_total')}",
        f"Decision useful: {card.get('decision_useful')}",
        f"Regimes: {card.get('regime_count')} | Weeks covered: {card.get('weeks_covered')}",
        "",
        "## Horizon Results",
    ]
    for row in card.get("by_horizon", []):
        lines.append(
            f"- {row.get('horizon_days')}D: n={row.get('n')}, hit={row.get('hit_rate_pct')}%, "
            f"avg_R={row.get('avg_return_R')}, avg_return={row.get('avg_return_pct')}%"
        )
    lines += ["", "## Benchmark Adjusted"]
    for row in card.get("benchmark_adjusted_by_horizon", []):
        lines.append(
            f"- {row.get('horizon_days')}D: n={row.get('n')}, excess_hit={row.get('excess_hit_rate_pct')}%, "
            f"avg_excess_R={row.get('avg_excess_return_R')}"
        )
    lines += ["", "## Slippage Adjusted"]
    for row in card.get("slippage_adjusted_by_horizon", []):
        lines.append(
            f"- {row.get('horizon_days')}D: n={row.get('n')}, hit={row.get('slippage_adjusted_hit_rate_pct')}%, "
            f"avg_slip_R={row.get('avg_slippage_adjusted_return_R')}"
        )
    lines += ["", "## Required Next Evidence"]
    lines.extend(f"- {item}" for item in card.get("required_next_evidence", []))
    lines += ["", card.get("methodology_caveat", DISCLAIMER)]
    return "\n".join(lines).rstrip() + "\n"


def write_horizon_scorecard(slippage_bps: float = DEFAULT_SLIPPAGE_BPS) -> dict[str, Any]:
    resolution = resolve_pending_observations(slippage_bps=slippage_bps)
    card = _scorecard(_resolved_rows(), resolution)
    _write_json(HORIZON_JSON, card)
    (REPORTS / HORIZON_MD).write_text(_markdown(card))
    summarize_forward_evidence(write=True)
    return card


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Research-only forward paper evidence ledger")
    ap.add_argument("--log-latest", action="store_true", help="Log latest recommender picks as pending observations")
    ap.add_argument("--scorecard", action="store_true", help="Resolve pending observations and write horizon scorecard")
    ap.add_argument("--summary", action="store_true", help="Write/read evidence summary")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.log_latest:
        out = log_latest_super_smart(top=args.top, refresh=args.refresh)
    elif args.scorecard:
        out = write_horizon_scorecard()
    else:
        out = summarize_forward_evidence()
    print(json.dumps(out, indent=2, sort_keys=True, default=str) if args.json else json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
