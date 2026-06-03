#!/usr/bin/env python3
"""Alpaca paper-broker READ-ONLY mirror.

This script intentionally performs **no broker writes**. Earlier versions could
POST to /v2/orders after local safety checks; that still violated the V3 single
order path invariant. The only legal order path is:

    execution.order_manager.OrderManager.submit(...)

Until a real Alpaca adapter implementing `execution.broker_base.BrokerAdapter`
is built and injected into OrderManager, this script may only:
  - check Alpaca connectivity/account/positions,
  - compare local paper positions vs Alpaca positions,
  - report would-be mirror actions.

It cannot submit, cancel, or close orders.
"""
from __future__ import annotations
import json
import os
import sys
from datetime import date
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))        # scripts/  -> db
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))    # repo root -> safety
from db import kb
from safety import config_guard
from safety.logging_setup import get_logger

log = get_logger("broker")
KEY = os.environ.get("APCA_API_KEY_ID")
SEC = os.environ.get("APCA_API_SECRET_KEY")
DEFAULT_BASE = "https://paper-api.alpaca.markets/v2"
BASE = os.environ.get("APCA_API_BASE_URL", DEFAULT_BASE).rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "alpaca-mirror.json"


def validate_base_url(base: str = BASE) -> str:
    """Read-only mirror may only target the Alpaca paper trading API."""
    normalized = base.rstrip("/")
    if normalized != DEFAULT_BASE:
        raise RuntimeError(
            "Alpaca mirror refuses non-paper endpoint; expected "
            f"{DEFAULT_BASE}, got {normalized}"
        )
    return normalized


def api_url(path: str) -> str:
    suffix = "/" + path.lstrip("/")
    if suffix.startswith("/v2/"):
        suffix = suffix[3:]
    return f"{validate_base_url()}{suffix}"


def auth_headers() -> dict:
    return {"APCA-API-KEY-ID": KEY or "", "APCA-API-SECRET-KEY": SEC or ""}


def _get(path: str):
    r = requests.get(api_url(path), headers=auth_headers(), timeout=15)
    r.raise_for_status()
    return r.json()


def list_alpaca_positions() -> list[dict]:
    return _get("/positions")


def get_account() -> dict:
    return _get("/account")


def submit_order(*_args, **_kwargs):
    """Forbidden compatibility stub. Do not call this from production code."""
    raise RuntimeError("Alpaca writes are disabled; route orders through execution.order_manager")


def main():
    if not (KEY and SEC):
        print("Alpaca: APCA_API_KEY_ID + APCA_API_SECRET_KEY not set; read-only no-op.")
        OUT.write_text(json.dumps({"connected": False, "reason": "no keys", "write_enabled": False}))
        return

    # This check is still useful: if the safety core says trading is blocked, the
    # report should make that visible. It does NOT enable writes.
    ok, reasons = config_guard.safe_to_trade()
    try:
        acct = get_account()
        alp_positions = list_alpaca_positions()
    except Exception as e:
        log.error("alpaca_read_failed", extra={"error": str(e)})
        OUT.write_text(json.dumps({"connected": False, "error": str(e), "write_enabled": False}))
        return

    con = kb()
    open_local = con.execute(
        "SELECT ticker, entry, stop, COALESCE(risk_pct,1.0) FROM paper_positions WHERE status = 'OPEN'"
    ).fetchall()
    alp_by_sym = {p.get("symbol"): p for p in alp_positions}

    actions = []
    for ticker, entry, stop, rpct in open_local:
        if ticker in alp_by_sym:
            actions.append({"ticker": ticker, "action": "exists"})
        else:
            actions.append({
                "ticker": ticker,
                "action": "would_mirror_buy_read_only",
                "entry": float(entry) if entry is not None else None,
                "stop": float(stop) if stop is not None else None,
                "risk_pct": float(rpct) if rpct is not None else None,
                "blocked_by_safety": None if ok else reasons,
            })

    out = {
        "date": date.today().isoformat(),
        "connected": True,
        "write_enabled": False,
        "base_url": validate_base_url(),
        "single_order_path": "execution.order_manager.OrderManager.submit",
        "account_status": acct.get("status"),
        "equity": acct.get("equity"),
        "alpaca_positions": len(alp_positions),
        "local_open": len(open_local),
        "actions": actions,
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"Alpaca read-only mirror: {len(open_local)} local, {len(alp_positions)} broker positions; 0 writes.")


if __name__ == "__main__":
    main()
