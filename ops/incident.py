#!/usr/bin/env python3
"""Incident response. A critical incident blocks new entries, records an event,
updates safety state (pause), and alerts the operator.
"""
from __future__ import annotations
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import kill_switch
from monitoring import alerts
from journal import event_store

INCIDENT_TYPES = {
    "broker_disconnected": "high",
    "data_stale": "high",
    "reconciliation_failed": "critical",
    "stop_attach_failed": "critical",
    "unexpected_live_mode": "critical",
    "duplicate_order_attempt": "medium",
    "schema_mismatch": "high",
    "scorecard_source_mismatch": "high",
    "kill_switch_unreadable": "critical",
    "config_conflict": "high",
}
SEVERITY = ("low", "medium", "high", "critical")


def raise_incident(itype: str, detail: str = "", auto_halt: bool | None = None) -> dict:
    sev = INCIDENT_TYPES.get(itype, "medium")
    rec = {"ts": datetime.now(timezone.utc).isoformat(), "type": itype,
           "severity": sev, "detail": detail, "blocked_entries": False}
    # critical incidents block new entries (engage kill switch)
    if auto_halt is None:
        auto_halt = sev == "critical"
    if auto_halt:
        kill_switch.engage(f"incident:{itype}: {detail}")
        rec["blocked_entries"] = True
    alerts.alert(itype if itype in alerts.ALERT_TYPES else "order_rejected",
                 level="critical" if sev == "critical" else "warning", detail=detail)
    try:
        event_store.append("incident_raised", aggregate_type="incident",
                           aggregate_id=itype, payload=rec)
    except Exception:
        pass
    return rec


def blocks_new_entries() -> bool:
    """An active critical incident (kill switch engaged with incident reason)."""
    return kill_switch.is_halted()


if __name__ == "__main__":
    import json
    kill_switch.release()
    r = raise_incident("reconciliation_failed", "ghost AMD position")
    print(json.dumps(r, indent=2))
    print("blocks entries:", blocks_new_entries())
    kill_switch.release()
