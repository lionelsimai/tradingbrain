#!/usr/bin/env python3
"""Candidate-level data freshness scorecard.

This is a read-only audit layer. It does not fetch data, invent missing
fundamentals/news/social evidence, or change recommendations. It answers a
narrow integrity question: for the current research candidates, how fresh are
the local prices, fundamentals, news/catalyst documents, and social signals?
"""
from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import duckdb

from paths import KNOWLEDGE_DB, PRICES_DB, REPORTS_DIR, ROOT

PRICE_MAX_AGE_DAYS = 5
FUNDAMENTAL_MAX_AGE_DAYS = 45
NEWS_MAX_AGE_DAYS = 14
SOCIAL_MAX_AGE_DAYS = 7
ANALYST_TARGET_MAX_AGE_DAYS = 120

DISCLAIMER = (
    "Data-freshness badges are a research integrity overlay only. A green badge "
    "means local feeds are recent enough for review; it is not a buy signal and "
    "does not solve PIT/survivorship or forward-proof blockers."
)


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def infer_candidate_tickers(limit: int = 25) -> list[str]:
    """Infer current recommendation candidates from existing local reports."""
    tickers: list[str] = []

    def add(value: Any) -> None:
        if value is None:
            return
        if isinstance(value, str):
            parts = value.replace(",", " ").split()
            for part in parts:
                t = part.upper().strip()
                if t and t not in tickers and not t.startswith("^") and "=" not in t:
                    tickers.append(t)
            return
        if isinstance(value, dict):
            add(value.get("ticker") or value.get("symbol"))
            return
        if isinstance(value, (list, tuple)):
            for item in value:
                add(item)

    super_smart = _read_json(REPORTS_DIR / "super-smart-recommendations.json", {})
    add(super_smart.get("strict_current_picks"))
    add(super_smart.get("picks"))
    add(super_smart.get("watch_list"))

    pattern = _read_json(REPORTS_DIR / "ai-pattern-recommendations-latest.json", {})
    add(pattern.get("recommendations"))

    if not tickers:
        universe = _read_json(REPORTS_DIR / "ai-swing-hold-rank.json", {})
        add(universe.get("top") or universe.get("all"))

    return tickers[: int(limit)]


def _age_days(value: Any, now: datetime) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    ref = now.astimezone(timezone.utc).replace(tzinfo=None)
    return max(0, (ref.date() - dt.date()).days)


def _pct(num: int, den: int) -> float:
    return round((100.0 * num / den), 1) if den else 0.0


def _safe_table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    try:
        return {str(r[0]) for r in con.execute("SHOW TABLES").fetchall()}
    except Exception:
        return set()


def _query_map(db_path: Path, sql: str, params: list[Any], key_index: int = 0) -> dict[str, tuple]:
    if not db_path.exists():
        return {}
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return {}
    try:
        return {str(row[key_index]).upper(): row for row in con.execute(sql, params).fetchall() if row[key_index] is not None}
    except Exception:
        return {}
    finally:
        con.close()


def _available_table(db_path: Path, table: str) -> bool:
    if not db_path.exists():
        return False
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception:
        return False
    try:
        return table in _safe_table_names(con)
    finally:
        con.close()


def build_data_freshness_scorecard(
    tickers: list[str] | None = None,
    *,
    knowledge_db: str | Path = KNOWLEDGE_DB,
    prices_db: str | Path = PRICES_DB,
    now: datetime | None = None,
    write: bool = False,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    knowledge_db = Path(knowledge_db)
    prices_db = Path(prices_db)
    tickers = [str(t).upper().strip() for t in (tickers or infer_candidate_tickers()) if str(t).strip()]
    # Preserve order while removing duplicates/benchmarks.
    tickers = list(dict.fromkeys(t for t in tickers if not t.startswith("^") and "=" not in t))
    placeholders = ",".join(["?"] * len(tickers))

    price_rows: dict[str, tuple] = {}
    fact_rows: dict[str, tuple] = {}
    doc_rows: dict[str, tuple] = {}
    social_rows: dict[str, tuple] = {}
    target_rows: dict[str, tuple] = {}

    if tickers and _available_table(prices_db, "prices"):
        price_rows = _query_map(
            prices_db,
            f"SELECT ticker, MAX(date) AS max_date FROM prices WHERE ticker IN ({placeholders}) GROUP BY ticker",
            tickers,
        )
    if tickers and _available_table(knowledge_db, "facts"):
        fact_rows = _query_map(
            knowledge_db,
            f"SELECT ticker, MAX(as_of) AS max_asof, COUNT(*) AS n FROM facts WHERE ticker IN ({placeholders}) AND kind='fundamental' GROUP BY ticker",
            tickers,
        )
    if tickers and _available_table(knowledge_db, "documents"):
        doc_rows = _query_map(
            knowledge_db,
            f"""
            SELECT ticker, MAX(COALESCE(published_at, ingested_at)) AS max_doc_time,
                   SUM(CASE WHEN COALESCE(published_at, ingested_at) >= ? THEN 1 ELSE 0 END) AS recent_14d,
                   COUNT(*) AS total_docs
            FROM documents
            WHERE ticker IN ({placeholders})
            GROUP BY ticker
            """,
            [now.replace(tzinfo=None) - __import__("datetime").timedelta(days=NEWS_MAX_AGE_DAYS)] + tickers,
        )
    if tickers and _available_table(knowledge_db, "signals"):
        social_rows = _query_map(
            knowledge_db,
            f"""
            SELECT ticker, MAX(signal_date) AS max_signal_date, COUNT(*) AS n
            FROM signals
            WHERE ticker IN ({placeholders}) AND signal_name IN ('social_sentiment','x_sentiment')
            GROUP BY ticker
            """,
            tickers,
        )
    if tickers and _available_table(knowledge_db, "analyst_targets"):
        target_cutoff = (now.astimezone(timezone.utc).date() - timedelta(days=ANALYST_TARGET_MAX_AGE_DAYS))
        aggregate_expr = """
            (
                lower(coalesce(provenance_level, '')) IN ('provider_aggregate', 'consensus', 'aggregate')
                OR lower(coalesce(broker, '')) LIKE '%aggregate%'
                OR lower(coalesce(broker, '')) LIKE '%consensus%'
                OR lower(coalesce(analyst, '')) LIKE 'aggregate_%'
                OR (lower(coalesce(provider, '')) IN ('finnhub') AND lower(coalesce(provenance_level, '')) <> 'broker_analyst')
            )
        """
        independent_expr = f"""
            date >= ?
            AND target > 0
            AND NOT {aggregate_expr}
            AND length(trim(coalesce(broker, ''))) > 0
            AND length(trim(coalesce(analyst, ''))) > 0
            AND length(trim(coalesce(source_url, ''))) > 0
        """
        target_rows = _query_map(
            knowledge_db,
            f"""
            SELECT ticker,
                   MAX(date) AS max_target_date,
                   COUNT(*) AS n,
                   SUM(CASE WHEN date >= ? AND target > 0 THEN 1 ELSE 0 END) AS recent_target_rows,
                   SUM(CASE WHEN {independent_expr} THEN 1 ELSE 0 END) AS recent_independent_rows,
                   SUM(CASE WHEN date >= ? AND target > 0 AND {aggregate_expr} THEN 1 ELSE 0 END) AS recent_aggregate_rows,
                   MAX(CASE WHEN {independent_expr} THEN date ELSE NULL END) AS max_independent_date
            FROM analyst_targets
            WHERE ticker IN ({placeholders})
            GROUP BY ticker
            """,
            [target_cutoff, target_cutoff, target_cutoff, target_cutoff] + tickers,
        )

    rows: list[dict[str, Any]] = []
    counts = {
        "price_fresh": 0,
        "fundamentals_fresh": 0,
        "news_fresh": 0,
        "social_fresh": 0,
        "analyst_target_any_recent": 0,
        "analyst_target_independent_present": 0,
        "analyst_target_aggregate_only": 0,
        "green": 0,
        "yellow": 0,
        "red": 0,
    }

    for t in tickers:
        price_age = _age_days(price_rows.get(t, (None, None))[1] if t in price_rows else None, now)
        fundamental_age = _age_days(fact_rows.get(t, (None, None, 0))[1] if t in fact_rows else None, now)
        news_age = _age_days(doc_rows.get(t, (None, None, 0, 0))[1] if t in doc_rows else None, now)
        social_age = _age_days(social_rows.get(t, (None, None, 0))[1] if t in social_rows else None, now)
        target_tuple = target_rows.get(t, (None, None, 0, 0, 0, 0, None))
        target_age = _age_days(target_tuple[1] if t in target_rows else None, now)
        independent_target_age = _age_days(target_tuple[6] if t in target_rows and len(target_tuple) > 6 else None, now)
        recent_target_rows = int(target_tuple[3] or 0) if len(target_tuple) > 3 else 0
        recent_independent_rows = int(target_tuple[4] or 0) if len(target_tuple) > 4 else 0
        recent_aggregate_rows = int(target_tuple[5] or 0) if len(target_tuple) > 5 else 0

        price_ok = price_age is not None and price_age <= PRICE_MAX_AGE_DAYS
        fundamental_ok = fundamental_age is not None and fundamental_age <= FUNDAMENTAL_MAX_AGE_DAYS
        news_ok = news_age is not None and news_age <= NEWS_MAX_AGE_DAYS
        social_ok = social_age is not None and social_age <= SOCIAL_MAX_AGE_DAYS
        target_present = recent_target_rows > 0
        independent_target_present = recent_independent_rows > 0
        aggregate_only_target = target_present and not independent_target_present and recent_aggregate_rows > 0

        counts["price_fresh"] += int(price_ok)
        counts["fundamentals_fresh"] += int(fundamental_ok)
        counts["news_fresh"] += int(news_ok)
        counts["social_fresh"] += int(social_ok)
        counts["analyst_target_any_recent"] += int(target_present)
        counts["analyst_target_independent_present"] += int(independent_target_present)
        counts["analyst_target_aggregate_only"] += int(aggregate_only_target)

        missing_or_stale = []
        if not price_ok:
            missing_or_stale.append("price")
        if not fundamental_ok:
            missing_or_stale.append("fundamentals")
        if not news_ok:
            missing_or_stale.append("news")
        if not social_ok:
            missing_or_stale.append("social")
        if not independent_target_present:
            missing_or_stale.append("analyst_target_independent_provenance")

        if not price_ok or not news_ok:
            badge = "red"
            action = "do_not_raise_confidence_until_price/news_refreshed"
        elif fundamental_ok and social_ok:
            badge = "green"
            action = "fresh_enough_for_research_review"
        else:
            badge = "yellow"
            action = "research_only_discount_for_missing_or_stale_pillars"
        if badge == "green" and not independent_target_present:
            action = (
                "fresh_core_feeds_but_treat_targets_as_aggregate_only_discounted"
                if aggregate_only_target
                else "fresh_core_feeds_but_discount_for_missing_independent_target_provenance"
            )
        counts[badge] += 1

        doc_tuple = doc_rows.get(t, (None, None, 0, 0))
        rows.append({
            "ticker": t,
            "badge": badge,
            "price_age_days": price_age,
            "fundamental_age_days": fundamental_age,
            "news_age_days": news_age,
            "recent_documents_14d": int(doc_tuple[2] or 0) if len(doc_tuple) > 2 else 0,
            "social_signal_age_days": social_age,
            "analyst_target_age_days": target_age,
            "analyst_target_recent_rows": recent_target_rows,
            "analyst_target_independent_recent_rows": recent_independent_rows,
            "analyst_target_aggregate_recent_rows": recent_aggregate_rows,
            "analyst_target_independent_age_days": independent_target_age,
            "missing_or_stale": missing_or_stale,
            "action": action,
        })

    n = len(tickers)
    coverage = {
        "candidate_count": n,
        "price_fresh_pct": _pct(counts["price_fresh"], n),
        "fundamentals_fresh_pct": _pct(counts["fundamentals_fresh"], n),
        "news_fresh_pct": _pct(counts["news_fresh"], n),
        "social_fresh_pct": _pct(counts["social_fresh"], n),
        "analyst_target_any_recent_pct": _pct(counts["analyst_target_any_recent"], n),
        "analyst_target_independent_present_pct": _pct(counts["analyst_target_independent_present"], n),
        "analyst_target_aggregate_only_pct": _pct(counts["analyst_target_aggregate_only"], n),
        "green_badge_pct": _pct(counts["green"], n),
        "yellow_badge_pct": _pct(counts["yellow"], n),
        "red_badge_pct": _pct(counts["red"], n),
    }
    if n == 0:
        status = "no_candidates"
    elif coverage["price_fresh_pct"] < 80 or coverage["news_fresh_pct"] < 50:
        status = "stale_or_missing_critical"
    elif coverage["fundamentals_fresh_pct"] >= 80 and coverage["news_fresh_pct"] >= 80:
        status = "healthy"
    else:
        status = "partial"

    report = {
        "available": True,
        "mode": "candidate_data_freshness_scorecard_v1",
        "asof_utc": now.isoformat(),
        "status": status,
        "thresholds_days": {
            "price": PRICE_MAX_AGE_DAYS,
            "fundamentals": FUNDAMENTAL_MAX_AGE_DAYS,
            "news": NEWS_MAX_AGE_DAYS,
            "social": SOCIAL_MAX_AGE_DAYS,
            "analyst_targets": ANALYST_TARGET_MAX_AGE_DAYS,
        },
        "coverage": coverage,
        "rows": rows,
        "top_stale_or_missing": [r for r in rows if r["badge"] != "green" or r.get("missing_or_stale")][:15],
        "report_paths": {
            "json": str(REPORTS_DIR / "data-freshness-latest.json"),
            "markdown": str(REPORTS_DIR / "data-freshness-latest.md"),
        },
        "disclaimer": DISCLAIMER,
    }
    if write:
        write_reports(report)
    return report


def format_markdown(report: dict[str, Any]) -> str:
    cov = report.get("coverage", {})
    lines = [
        "# TradingBrain Candidate Data Freshness Scorecard",
        f"_{report.get('asof_utc', '')}_",
        "",
        f"Status: **{report.get('status')}** · candidates={cov.get('candidate_count', 0)} · research-only",
        "",
        "## Coverage",
        f"- Fresh prices: {cov.get('price_fresh_pct')}%",
        f"- Fresh fundamentals: {cov.get('fundamentals_fresh_pct')}%",
        f"- Fresh news/catalyst docs: {cov.get('news_fresh_pct')}%",
        f"- Fresh social signals: {cov.get('social_fresh_pct')}%",
        f"- Any recent analyst target rows: {cov.get('analyst_target_any_recent_pct')}%",
        f"- Independent analyst target provenance present: {cov.get('analyst_target_independent_present_pct')}% (provider aggregates do not count as independent)",
        f"- Aggregate-only analyst target rows: {cov.get('analyst_target_aggregate_only_pct')}%",
        "",
        "## Candidate badges",
        "| Ticker | Badge | Price age | Fundamental age | News age | Recent docs | Social age | Target rows | Independent target rows | Missing/stale | Action |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in report.get("rows", []):
        lines.append(
            f"| {row.get('ticker')} | {row.get('badge')} | {row.get('price_age_days')} | "
            f"{row.get('fundamental_age_days')} | {row.get('news_age_days')} | "
            f"{row.get('recent_documents_14d')} | {row.get('social_signal_age_days')} | "
            f"{row.get('analyst_target_recent_rows')} | {row.get('analyst_target_independent_recent_rows')} | "
            f"{', '.join(row.get('missing_or_stale') or []) or '-'} | {row.get('action')} |"
        )
    lines += ["", "## Caveat", f"- {report.get('disclaimer', DISCLAIMER)}"]
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any]) -> dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "data-freshness-latest.json").write_text(json.dumps(report, indent=2, default=str))
    (REPORTS_DIR / "data-freshness-latest.md").write_text(format_markdown(report))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="*", help="Optional tickers; defaults to inferred current candidates")
    ap.add_argument("--write", action="store_true", help="Write reports/data-freshness-latest.{json,md}")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    tickers = args.tickers if args.tickers else None
    report = build_data_freshness_scorecard(tickers=tickers, write=args.write)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        cov = report.get("coverage", {})
        print(
            f"Data freshness: status={report.get('status')} candidates={cov.get('candidate_count')} "
            f"price={cov.get('price_fresh_pct')}% fundamentals={cov.get('fundamentals_fresh_pct')}% "
            f"news={cov.get('news_fresh_pct')}% social={cov.get('social_fresh_pct')}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
