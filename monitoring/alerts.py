#!/usr/bin/env python3
"""Alert routing. Alerts are recorded to reports/alerts.jsonl and (optionally)
surfaced to the operator. No external delivery here — that is wired by the host."""
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import REPORTS_DIR

ALERTS_FILE = REPORTS_DIR / "alerts.jsonl"
LEVELS = ("info", "warning", "critical")

ALERT_TYPES = {
    "kill_switch_engaged", "stale_data", "broker_disconnected", "order_rejected",
    "stop_attach_failed", "reconciliation_mismatch", "daily_loss_near_breach",
    "drawdown_near_breach", "repeated_strategy_failures",
}


def alert(atype: str, level: str = "warning", detail: str = "", **extra) -> dict:
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "type": atype,
           "level": level if level in LEVELS else "warning", "detail": detail, **extra}
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    with ALERTS_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def recent(n: int = 20) -> list[dict]:
    if not ALERTS_FILE.exists():
        return []
    return [json.loads(l) for l in ALERTS_FILE.read_text().splitlines()[-n:]]


if __name__ == "__main__":
    print(alert("stale_data", "critical", "NVDA quote 9999s old"))
