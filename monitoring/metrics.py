#!/usr/bin/env python3
"""Operational metrics. Counters + gauges written to reports/metrics.json so the
operator (and tests) can read system health at a glance.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import REPORTS_DIR

METRICS_FILE = REPORTS_DIR / "metrics.json"

_DEFAULT = {
    "order_rejection_count": 0, "order_approval_count": 0, "fill_count": 0,
    "stale_quote_count": 0, "reconciliation_mismatches": 0,
    "slippage_bps_sum": 0.0, "slippage_samples": 0,
    "drawdown_pct": 0.0, "daily_pnl": 0.0, "portfolio_heat_pct": 0.0,
    "kill_switch_engaged": False,
}


def _load() -> dict:
    if METRICS_FILE.exists():
        try:
            return {**_DEFAULT, **json.loads(METRICS_FILE.read_text())}
        except Exception:
            pass
    return dict(_DEFAULT)


def incr(key: str, by: float = 1):
    m = _load(); m[key] = m.get(key, 0) + by; _save(m)


def gauge(key: str, value):
    m = _load(); m[key] = value; _save(m)


def record_slippage(bps: float):
    m = _load(); m["slippage_bps_sum"] += bps; m["slippage_samples"] += 1; _save(m)


def _save(m: dict):
    m["updated_at"] = datetime.now(timezone.utc).isoformat()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    METRICS_FILE.write_text(json.dumps(m, indent=2))


def snapshot() -> dict:
    m = _load()
    m["avg_slippage_bps"] = round(m["slippage_bps_sum"] / m["slippage_samples"], 2) if m["slippage_samples"] else 0.0
    return m


if __name__ == "__main__":
    incr("order_approval_count"); record_slippage(5.2)
    print(json.dumps(snapshot(), indent=2))
