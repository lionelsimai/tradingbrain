#!/usr/bin/env python3
"""Append-only audit trail. For every trade the system can reconstruct: why it
was proposed, which agent/strategy, which risk checks passed, the size math, the
order, the fill, the exit, and the final P&L.

Storage: reports/journal/trade_journal.jsonl (one event per line, never mutated).
Each event carries a code commit/version hash for full provenance.
"""
from __future__ import annotations
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
JOURNAL = ROOT / "reports" / "journal" / "trade_journal.jsonl"

_EVENTS = ("idea", "risk_decision", "order", "fill", "exit", "error", "override")


def _code_version() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    # Fallback: hash of the safety package mtime set (deterministic-ish provenance).
    return os.environ.get("TB_CODE_VERSION", "nogit")


def log(event_type: str, client_order_id: str, payload: dict) -> dict:
    """Append one immutable event. Returns the written record."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event_type,
        "client_order_id": client_order_id,
        "code_version": _code_version(),
        "mode": os.environ.get("TB_MODE", "paper"),
        "payload": payload,
    }
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open("a") as f:
        f.write(json.dumps(rec, default=str) + "\n")
    return rec


def log_idea(client_order_id, idea: dict):
    return log("idea", client_order_id, idea)


def log_risk(client_order_id, decision: dict):
    return log("risk_decision", client_order_id, decision)


def log_order(client_order_id, order: dict):
    return log("order", client_order_id, order)


def log_fill(client_order_id, fill: dict):
    return log("fill", client_order_id, fill)


def log_exit(client_order_id, exit_info: dict):
    return log("exit", client_order_id, exit_info)


def reconstruct(client_order_id: str) -> list[dict]:
    """All events for one trade, in order — the audit reconstruction."""
    if not JOURNAL.exists():
        return []
    out = []
    for line in JOURNAL.read_text().splitlines():
        try:
            rec = json.loads(line)
            if rec.get("client_order_id") == client_order_id:
                out.append(rec)
        except Exception:
            continue
    return out


def tail(n: int = 20) -> list[dict]:
    if not JOURNAL.exists():
        return []
    lines = JOURNAL.read_text().splitlines()[-n:]
    return [json.loads(x) for x in lines if x.strip()]


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        for rec in reconstruct(sys.argv[1]):
            print(json.dumps(rec, indent=2))
    else:
        for rec in tail(20):
            print(f"{rec['ts']} {rec['event']:14} {rec['client_order_id']}")
