#!/usr/bin/env python3
"""Analyst target ingest.

Currently supports Finnhub's aggregate price-target endpoint. These rows are
stored with ``provenance_level='provider_aggregate'`` so downstream provenance
and target-quality checks discount them. They are useful for freshness/context,
but they do not satisfy independent broker/analyst evidence gates.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import duckdb
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from paths import DATA_DIR, KNOWLEDGE_DB, REPORTS_DIR, ROOT  # noqa: E402
from scripts.data_freshness import infer_candidate_tickers  # noqa: E402

BASE = "https://finnhub.io/api/v1"
RAW_DIR = DATA_DIR / "raw" / "analyst_targets"
OUT_JSON = REPORTS_DIR / "analyst-target-ingest-latest.json"
OUT_MD = REPORTS_DIR / "analyst-target-ingest-latest.md"

DISCLAIMER = (
    "Finnhub price-target rows are provider aggregate/consensus evidence. They "
    "are not independent broker/analyst provenance and must remain discounted by "
    "TradingBrain target-quality checks."
)

TARGET_COLUMNS: dict[str, str] = {
    "target_id": "VARCHAR",
    "ticker": "VARCHAR",
    "broker": "VARCHAR",
    "analyst": "VARCHAR",
    "rating": "VARCHAR",
    "action": "VARCHAR",
    "target": "DOUBLE",
    "date": "DATE",
    "source_url": "VARCHAR",
    "notes": "VARCHAR",
    "provider": "VARCHAR",
    "provenance_level": "VARCHAR",
    "source_json": "JSON",
    "ingested_at": "TIMESTAMP",
}


def _api_key() -> str | None:
    for name in ("FINNHUB_API_KEY", "FINNHUB", "finnhub", "finnhub_api_key"):
        value = os.environ.get(name)
        if value:
            return value
    return None


def _ticker(value: Any) -> str:
    return str(value or "").upper().strip()


def _target_id(*parts: Any) -> str:
    return hashlib.sha256("||".join(str(p) for p in parts).encode()).hexdigest()[:32]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return date.today().isoformat()
    return text[:10]


def _parse_finnhub_payload(ticker: str, payload: dict[str, Any], *, fetched_at: datetime | None = None) -> list[dict[str, Any]]:
    """Convert Finnhub aggregate payload into normalized aggregate rows."""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    symbol = _ticker(payload.get("symbol") or ticker)
    if not symbol:
        return []
    published = _date(payload.get("lastUpdated") or payload.get("updated") or fetched_at)
    source_url = f"{BASE}/stock/price-target?symbol={symbol}"
    metrics = [
        ("median", payload.get("targetMedian"), "aggregate_median"),
        ("mean", payload.get("targetMean"), "aggregate_mean"),
        ("high", payload.get("targetHigh"), "aggregate_high"),
        ("low", payload.get("targetLow"), "aggregate_low"),
    ]
    rows: list[dict[str, Any]] = []
    for label, raw_target, analyst_name in metrics:
        target = _float(raw_target)
        if target is None or target <= 0:
            continue
        rows.append({
            "target_id": _target_id("finnhub", symbol, label, published, target),
            "ticker": symbol,
            "broker": "Finnhub consensus aggregate",
            "analyst": analyst_name,
            "rating": "consensus",
            "action": f"provider aggregate {label} target",
            "target": target,
            "date": published,
            "source_url": source_url,
            "notes": "Provider aggregate price-target metric; not broker/analyst-level provenance.",
            "provider": "finnhub",
            "provenance_level": "provider_aggregate",
            "source_json": json.dumps(payload, sort_keys=True, default=str),
            "ingested_at": fetched_at.isoformat(),
        })
    return rows


def fetch_finnhub_price_targets(
    tickers: list[str],
    *,
    key: str | None = None,
    session: Any = requests,
    throttle_seconds: float = 0.1,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fetch Finnhub aggregate price targets.

    Returns ``(rows, errors)``. Missing API key is reported as an error and does
    not raise, so Hermes/tool calls can fail closed without leaking secrets.
    """
    api_key = key or _api_key()
    clean = list(dict.fromkeys(_ticker(t) for t in tickers if _ticker(t)))
    if not api_key:
        return [], [{"ticker": None, "error": "FINNHUB_API_KEY not set"}]

    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for ticker in clean:
        try:
            response = session.get(
                f"{BASE}/stock/price-target",
                params={"symbol": ticker, "token": api_key},
                timeout=15,
            )
            if getattr(response, "status_code", 200) == 429:
                time.sleep(max(0.0, throttle_seconds * 2))
                response = session.get(
                    f"{BASE}/stock/price-target",
                    params={"symbol": ticker, "token": api_key},
                    timeout=15,
                )
            if getattr(response, "status_code", 200) != 200:
                errors.append({"ticker": ticker, "error": f"status {getattr(response, 'status_code', 'unknown')}"})
                continue
            payload = response.json() or {}
            parsed = _parse_finnhub_payload(ticker, payload)
            if parsed:
                rows.extend(parsed)
            else:
                errors.append({"ticker": ticker, "error": "no positive aggregate target values returned"})
        except Exception as exc:
            errors.append({"ticker": ticker, "error": str(exc)})
        time.sleep(max(0.0, throttle_seconds))
    return rows, errors


def ensure_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS analyst_targets(
            target_id VARCHAR,
            ticker VARCHAR,
            broker VARCHAR,
            analyst VARCHAR,
            rating VARCHAR,
            action VARCHAR,
            target DOUBLE,
            date DATE,
            source_url VARCHAR,
            notes VARCHAR,
            provider VARCHAR,
            provenance_level VARCHAR,
            source_json JSON,
            ingested_at TIMESTAMP
        )
        """
    )
    existing = {str(r[0]) for r in con.execute("DESCRIBE analyst_targets").fetchall()}
    for name, dtype in TARGET_COLUMNS.items():
        if name not in existing:
            con.execute(f'ALTER TABLE analyst_targets ADD COLUMN "{name}" {dtype}')
    try:
        con.execute("CREATE INDEX IF NOT EXISTS idx_analyst_targets_ticker_date ON analyst_targets(ticker, date)")
    except Exception:
        pass


def _write_jsonl(rows: list[dict[str, Any]]) -> Path | None:
    if not rows:
        return None
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / "targets.jsonl"
    with path.open("a") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")
    return path


def merge_targets(
    rows: list[dict[str, Any]],
    *,
    db_path: str | Path = KNOWLEDGE_DB,
    write_raw: bool = True,
) -> dict[str, Any]:
    """Merge normalized target rows into knowledge.duckdb idempotently."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        ensure_schema(con)
        added = 0
        updated = 0
        for row in rows:
            target_id = str(row.get("target_id") or "")
            if not target_id:
                continue
            existed = int(con.execute("SELECT COUNT(*) FROM analyst_targets WHERE target_id = ?", [target_id]).fetchone()[0] or 0)
            con.execute("DELETE FROM analyst_targets WHERE target_id = ?", [target_id])
            con.execute(
                """
                INSERT INTO analyst_targets
                (target_id, ticker, broker, analyst, rating, action, target, date,
                 source_url, notes, provider, provenance_level, source_json, ingested_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    target_id,
                    _ticker(row.get("ticker")),
                    row.get("broker") or "",
                    row.get("analyst") or "",
                    row.get("rating") or "",
                    row.get("action") or "",
                    _float(row.get("target")),
                    _date(row.get("date")),
                    row.get("source_url") or "",
                    row.get("notes") or "",
                    row.get("provider") or "",
                    row.get("provenance_level") or "",
                    row.get("source_json") if isinstance(row.get("source_json"), str) else json.dumps(row.get("source_json") or {}, default=str),
                    row.get("ingested_at") or datetime.now(timezone.utc).isoformat(),
                ],
            )
            if existed:
                updated += 1
            else:
                added += 1
        raw_path = _write_jsonl(rows) if write_raw else None
        total = int(con.execute("SELECT COUNT(*) FROM analyst_targets").fetchone()[0] or 0)
        aggregate_total = int(
            con.execute("SELECT COUNT(*) FROM analyst_targets WHERE lower(coalesce(provenance_level, '')) = 'provider_aggregate'").fetchone()[0] or 0
        )
    finally:
        con.close()
    return {
        "added": added,
        "updated": updated,
        "total": total,
        "db_total": total,
        "provider_aggregate_total": aggregate_total,
        "raw_jsonl": str(raw_path) if raw_path else None,
        "disclaimer": DISCLAIMER,
    }


def render_md(report: dict[str, Any]) -> str:
    lines = [
        "# Analyst Target Ingest",
        "",
        f"Generated: {report.get('asof')}",
        f"Provider: {report.get('provider')}",
        f"Tickers requested: {len(report.get('tickers') or [])}",
        f"Rows fetched: {report.get('valid_rows')}",
        f"Errors: {len(report.get('errors') or [])}",
        "",
        "## Merge",
    ]
    merge = report.get("merge") or {}
    for key in ("added", "updated", "db_total", "provider_aggregate_total", "raw_jsonl"):
        lines.append(f"- {key}: {merge.get(key)}")
    lines += ["", "## Caution", f"- {report.get('caution', DISCLAIMER)}"]
    if report.get("errors"):
        lines += ["", "## Errors"]
        for err in report.get("errors", [])[:20]:
            lines.append(f"- {err.get('ticker')}: {err.get('error')}")
    return "\n".join(lines).rstrip() + "\n"


def write_reports(report: dict[str, Any]) -> dict[str, str]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render_md(report))
    return {"json": str(OUT_JSON), "markdown": str(OUT_MD)}


def run_ingest(tickers: list[str] | None = None, *, provider: str = "finnhub", key: str | None = None) -> dict[str, Any]:
    if provider != "finnhub":
        return {
            "available": False,
            "provider": provider,
            "error": "only provider='finnhub' is implemented",
            "disclaimer": DISCLAIMER,
        }
    selected = tickers or infer_candidate_tickers(limit=25)
    rows, errors = fetch_finnhub_price_targets(selected, key=key)
    merge = merge_targets(rows) if rows else {"added": 0, "updated": 0, "total": 0, "db_total": 0, "provider_aggregate_total": 0}
    report = {
        "available": bool(rows) or not errors,
        "asof": datetime.now(timezone.utc).isoformat(),
        "provider": provider,
        "tickers": selected,
        "valid_rows": len(rows),
        "errors": errors,
        "merge": merge,
        "caution": DISCLAIMER,
        "disclaimer": DISCLAIMER,
    }
    write_reports(report)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Ingest analyst target evidence")
    ap.add_argument("--tickers", nargs="*", help="Optional ticker list; defaults to current candidates")
    ap.add_argument("--provider", default="finnhub")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run_ingest(tickers=args.tickers or None, provider=args.provider)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(
            f"Analyst target ingest: provider={report.get('provider')} "
            f"rows={report.get('valid_rows')} errors={len(report.get('errors') or [])}"
        )
        print(f"Caution: {DISCLAIMER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
