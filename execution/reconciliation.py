#!/usr/bin/env python3
"""Reconciliation — compare internal state vs broker state and classify mismatches.
A blocking mismatch prevents new entries; an incident triggers pause/kill.
"""
from __future__ import annotations
from dataclasses import dataclass, field

SEVERITY = ("info", "warning", "blocking", "incident")

# mismatch type -> default severity
SEVERITY_MAP = {
    "ghost_position": "incident",        # broker has a position we don't track
    "missing_broker_position": "blocking",
    "missing_internal_position": "incident",
    "untracked_fill": "blocking",
    "stale_open_order": "warning",
    "missing_stop": "incident",
    "orphan_stop": "warning",
    "cash_mismatch": "warning",
    "quantity_mismatch": "blocking",
    "avg_price_mismatch": "info",
}


@dataclass
class ReconResult:
    ok: bool = True
    mismatches: list[dict] = field(default_factory=list)
    worst: str = "info"

    def add(self, mtype: str, detail: str):
        sev = SEVERITY_MAP.get(mtype, "warning")
        self.mismatches.append({"type": mtype, "severity": sev, "detail": detail})
        if SEVERITY.index(sev) > SEVERITY.index(self.worst):
            self.worst = sev
        if sev in ("blocking", "incident"):
            self.ok = False

    @property
    def blocks_entries(self) -> bool:
        return any(m["severity"] in ("blocking", "incident") for m in self.mismatches)

    @property
    def is_incident(self) -> bool:
        return any(m["severity"] == "incident" for m in self.mismatches)


def reconcile(internal_positions: list[dict], broker_positions: list[dict],
              internal_orders: list[dict] | None = None,
              broker_orders: list[dict] | None = None,
              internal_cash: float | None = None,
              broker_cash: float | None = None,
              qty_tol: float = 1e-6, cash_tol: float = 1.0) -> ReconResult:
    r = ReconResult()
    bi = {p["symbol"]: p for p in broker_positions}
    ii = {p["symbol"]: p for p in internal_positions}

    for sym, bp in bi.items():
        if sym not in ii:
            r.add("ghost_position", f"{sym} at broker, not tracked internally")
        else:
            iq, bq = float(ii[sym].get("qty", 0)), float(bp.get("qty", 0))
            if abs(iq - bq) > qty_tol:
                r.add("quantity_mismatch", f"{sym}: internal {iq} vs broker {bq}")
            if ii[sym].get("stop") in (None, 0) and bp.get("qty"):
                r.add("missing_stop", f"{sym}: open broker position without stop")
    for sym in ii:
        if sym not in bi:
            r.add("missing_broker_position", f"{sym} tracked internally, absent at broker")

    if internal_cash is not None and broker_cash is not None:
        if abs(internal_cash - broker_cash) > cash_tol:
            r.add("cash_mismatch", f"internal ${internal_cash:.2f} vs broker ${broker_cash:.2f}")

    bo = {o.get("client_order_id") for o in (broker_orders or [])}
    for o in (internal_orders or []):
        if o.get("status") in ("submitted", "accepted") and o.get("client_order_id") not in bo:
            r.add("stale_open_order", f"order {o.get('client_order_id')} not at broker")
    return r


if __name__ == "__main__":
    import json
    r = reconcile(
        internal_positions=[{"symbol": "NVDA", "qty": 40, "stop": 206}],
        broker_positions=[{"symbol": "NVDA", "qty": 45}, {"symbol": "AMD", "qty": 10}],
    )
    print(json.dumps({"ok": r.ok, "worst": r.worst, "blocks": r.blocks_entries,
                      "mismatches": r.mismatches}, indent=2))
