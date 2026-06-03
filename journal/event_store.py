#!/usr/bin/env python3
"""Append-only event store. Every order decision/fill/rejection/operator action
is an immutable event. Order state is RECONSTRUCTED from events, so the system
can recover after a crash and prove what happened.

Each event is chained (previous_event_id) and checksummed so partial writes or
tampering are detectable.

Storage: reports/journal/events.jsonl
"""
from __future__ import annotations
import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

try:
    from paths import JOURNAL_DIR
except Exception:
    JOURNAL_DIR = Path(__file__).resolve().parents[1] / "reports" / "journal"

JOURNAL_DIR.mkdir(parents=True, exist_ok=True)
EVENTS = JOURNAL_DIR / "events.jsonl"

ORDER_EVENT_TYPES = {
    "signal_created", "order_proposed", "config_checked", "kill_switch_checked",
    "data_checked", "portfolio_checked", "risk_checked", "human_review_required",
    "human_review_approved", "human_review_rejected", "order_approved",
    "order_rejected", "order_submitted", "broker_state_checked",
    "order_submit_failed", "broker_acknowledged",
    "order_partially_filled", "order_filled", "order_cancelled",
    "order_rejected_by_broker", "stop_attached", "target_attached",
    "stop_attach_failed", "target_attach_failed", "position_opened",
    "position_updated", "exit_signal_created", "exit_order_proposed",
    "exit_order_submitted", "position_closed", "reconciliation_started",
    "reconciliation_passed", "reconciliation_failed", "journal_complete",
    "operator_action", "incident_raised", "incident_block_checked",
}


def _checksum(d: dict) -> str:
    raw = json.dumps({k: v for k, v in d.items() if k != "checksum"},
                     sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _last_event_id() -> str | None:
    if not EVENTS.exists():
        return None
    last = None
    with EVENTS.open() as f:
        for line in f:
            line = line.strip()
            if line:
                last = line
    if not last:
        return None
    try:
        return json.loads(last)["event_id"]
    except Exception:
        return None


def append(event_type: str, aggregate_id: str, payload: dict, *,
           aggregate_type: str = "order", mode: str | None = None,
           source: str = "order_manager", actor: str = "system",
           policy_version: str | None = None, code_version: str | None = None) -> dict:
    if event_type not in ORDER_EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type}")
    ev = {
        "event_id": "ev_" + uuid.uuid4().hex[:16],
        "event_type": event_type,
        "aggregate_type": aggregate_type,
        "aggregate_id": aggregate_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mode": mode or os.environ.get("TB_MODE", "paper"),
        "source": source,
        "actor": actor,
        "policy_version": policy_version,
        "code_version": code_version,
        "payload": payload,
        "previous_event_id": _last_event_id(),
    }
    ev["checksum"] = _checksum(ev)
    with EVENTS.open("a") as f:
        f.write(json.dumps(ev, default=str) + "\n")
    return ev


def read_all() -> list[dict]:
    if not EVENTS.exists():
        return []
    out = []
    with EVENTS.open() as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def events_for(aggregate_id: str) -> list[dict]:
    return [e for e in read_all() if e["aggregate_id"] == aggregate_id]


def reconstruct(aggregate_id: str) -> dict:
    """Rebuild current state of an order purely from its event chain."""
    evs = events_for(aggregate_id)
    state = {"aggregate_id": aggregate_id, "status": "unknown", "events": len(evs),
             "filled_qty": 0, "rejections": [], "history": []}
    for e in evs:
        t = e["event_type"]
        state["history"].append(t)
        if t == "order_approved":
            state["status"] = "approved"
        elif t == "order_rejected":
            state["status"] = "rejected"
            state["rejections"].append(e["payload"].get("reason"))
        elif t == "order_submitted":
            state["status"] = "submitted"
        elif t == "order_partially_filled":
            state["status"] = "partially_filled"
            state["filled_qty"] = e["payload"].get("filled_qty", state["filled_qty"])
        elif t == "order_filled":
            state["status"] = "filled"
            state["filled_qty"] = e["payload"].get("filled_qty", state["filled_qty"])
        elif t == "order_cancelled":
            state["status"] = "cancelled"
        elif t == "position_closed":
            state["status"] = "closed"
    return state


def verify_integrity() -> dict:
    """Check every event's checksum and chain linkage."""
    evs = read_all()
    bad_checksum, broken_chain = [], []
    prev = None
    for e in evs:
        if e.get("checksum") != _checksum(e):
            bad_checksum.append(e["event_id"])
        if e.get("previous_event_id") != prev:
            broken_chain.append(e["event_id"])
        prev = e["event_id"]
    return {"events": len(evs), "bad_checksum": bad_checksum,
            "broken_chain": broken_chain,
            "ok": not bad_checksum and not broken_chain}


if __name__ == "__main__":
    print(json.dumps(verify_integrity(), indent=2))
