#!/usr/bin/env python3
"""Live market-data provider health checks.

This module is deliberately market-data only. It checks whether real-time quote
dependencies are installed, reachable, and producing fresh snapshots, then writes
machine-readable evidence for readiness dashboards and go-live blockers.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from paths import DATA_DIR, REPORTS_DIR, ROOT

SNAPSHOT = DATA_DIR / "intraday_snap.parquet"
MOOMOO_REPORT = REPORTS_DIR / "moomoo-live-quotes.json"
OUT = REPORTS_DIR / "live-data-health.json"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 11111
DEFAULT_MAX_QUOTE_AGE_SECONDS = 15 * 60


def _env_file_values() -> dict[str, str]:
    values: dict[str, str] = {}
    env_path = ROOT / ".env"
    if not env_path.exists():
        return values
    for raw in env_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.split("#", 1)[0].strip().strip("'\"")
    return values


def _env(name: str, default: str) -> str:
    return os.environ.get(name) or _env_file_values().get(name) or default


def configured_host_port(host: str | None = None, port: int | None = None) -> tuple[str, int]:
    h = host or _env("MOOMOO_OPEND_HOST", DEFAULT_HOST)
    raw_port = str(port if port is not None else _env("MOOMOO_OPEND_PORT", str(DEFAULT_PORT)))
    try:
        p = int(raw_port)
    except ValueError:
        p = DEFAULT_PORT
    return h, p


def _port_open(host: str, port: int, timeout_s: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def _package_status() -> dict[str, Any]:
    moomoo = importlib.util.find_spec("moomoo")
    futu = importlib.util.find_spec("futu")
    return {
        "package_installed": bool(moomoo or futu),
        "module": "moomoo" if moomoo else ("futu" if futu else None),
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ts = pd.to_datetime(value, utc=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _snapshot_status(now: datetime) -> dict[str, Any]:
    status: dict[str, Any] = {
        "exists": SNAPSHOT.exists(),
        "path": str(SNAPSHOT),
        "rows": 0,
        "sources": [],
        "latest_quote_ts": None,
        "latest_fetch_ts": None,
        "quote_age_seconds": None,
    }
    if not SNAPSHOT.exists():
        return status
    try:
        df = pd.read_parquet(SNAPSHOT)
    except Exception as exc:
        status["read_error"] = str(exc)
        return status

    status["rows"] = int(len(df))
    if "source" in df.columns:
        status["sources"] = sorted(str(s) for s in df["source"].dropna().unique())
    for column, key in (("ts_utc", "latest_quote_ts"), ("fetched_at_utc", "latest_fetch_ts")):
        if column in df.columns and not df.empty:
            latest = _parse_ts(df[column].max())
            if latest:
                status[key] = latest.isoformat()
    latest_age_base = _parse_ts(status.get("latest_fetch_ts") or status.get("latest_quote_ts"))
    if latest_age_base:
        status["quote_age_seconds"] = max(0, int((now - latest_age_base).total_seconds()))
    return status


def check(
    *,
    require_realtime: bool = True,
    max_quote_age_seconds: int = DEFAULT_MAX_QUOTE_AGE_SECONDS,
    host: str | None = None,
    port: int | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    h, p = configured_host_port(host, port)
    pkg = _package_status()
    opend_reachable = _port_open(h, p)
    moomoo_report = _load_json(MOOMOO_REPORT)
    snapshot = _snapshot_status(now)
    tb_mode = _env("TB_MODE", "paper")
    tb_allow_live = _env("TB_ALLOW_LIVE", "0")
    hard_failures: list[str] = []
    warnings: list[str] = []

    if tb_mode == "live" or tb_allow_live == "1":
        hard_failures.append("live execution flags are enabled; live-data health refuses unsafe mode")
    if not pkg["package_installed"]:
        hard_failures.append("moomoo OpenAPI package is not installed")
    if require_realtime and not opend_reachable:
        hard_failures.append(f"moomoo OpenD is not reachable at {h}:{p}")
    if require_realtime and not moomoo_report:
        hard_failures.append("reports/moomoo-live-quotes.json is missing")
    if require_realtime and not snapshot["exists"]:
        hard_failures.append("data/intraday_snap.parquet is missing")
    if snapshot.get("read_error"):
        hard_failures.append(f"intraday snapshot unreadable: {snapshot['read_error']}")
    if snapshot["exists"] and snapshot["rows"] <= 0:
        hard_failures.append("intraday snapshot contains zero rows")
    if snapshot["exists"] and "moomoo:market_snapshot" not in snapshot["sources"]:
        warnings.append("intraday snapshot is not currently sourced from moomoo")
    quote_age = snapshot.get("quote_age_seconds")
    if require_realtime and quote_age is not None and quote_age > max_quote_age_seconds:
        hard_failures.append(
            f"intraday quote age {quote_age}s exceeds {max_quote_age_seconds}s freshness limit"
        )

    provider = {
        "name": "moomoo",
        "market": "US equities",
        "market_data_only": True,
        "host": h,
        "port": p,
        "package_installed": pkg["package_installed"],
        "module": pkg["module"],
        "opend_reachable": opend_reachable,
        "quote_report_exists": bool(moomoo_report),
        "quote_report_asof": moomoo_report.get("asof"),
        "quote_report_returned": moomoo_report.get("returned"),
    }
    ok = not hard_failures
    return {
        "asof": now.isoformat(),
        "ok": ok,
        "status": "PASS" if ok else "FAIL",
        "hard_failures": hard_failures,
        "warnings": warnings,
        "require_realtime": require_realtime,
        "max_quote_age_seconds": max_quote_age_seconds,
        "providers": {"moomoo": provider},
        "intraday_snapshot": snapshot,
        "safety": {
            "market_data_only": True,
            "tb_mode": tb_mode,
            "tb_allow_live": tb_allow_live,
            "live_trading_enabled": False,
        },
    }


def write(**kwargs: Any) -> dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = check(**kwargs)
    OUT.write_text(json.dumps(report, indent=2, default=str))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-report", action="store_true")
    ap.add_argument("--no-require-realtime", action="store_true")
    ap.add_argument("--max-age-seconds", type=int, default=DEFAULT_MAX_QUOTE_AGE_SECONDS)
    ap.add_argument("--host")
    ap.add_argument("--port", type=int)
    args = ap.parse_args(argv)
    kwargs = {
        "require_realtime": not args.no_require_realtime,
        "max_quote_age_seconds": args.max_age_seconds,
        "host": args.host,
        "port": args.port,
    }
    report = write(**kwargs) if args.write_report else check(**kwargs)
    print(json.dumps(report, indent=2, default=str))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main())
