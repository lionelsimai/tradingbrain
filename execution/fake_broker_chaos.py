#!/usr/bin/env python3
"""Hostile fake broker for execution chaos tests.

The adapter implements the normal BrokerAdapter contract but can return bad,
late, partial, duplicate, or protective-order-failure responses on purpose.
It never talks to a real broker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from execution.broker_base import BrokerAdapter, BrokerError
from safety.order import OrderIntent
from safety import incident_manager


class BrokerTimeout(BrokerError):
    """Broker did not respond in time; caller must reconcile state."""


class BrokerDisconnect(BrokerError):
    """Broker disconnected; caller must treat broker state as unknown."""


SCENARIOS = {
    "reject_order", "timeout_before_ack", "timeout_after_ack",
    "disconnect_before_fill", "disconnect_after_fill", "duplicate_ack",
    "duplicate_fill", "late_fill", "partial_fill", "bad_fill_price",
    "missing_fill_price", "missing_fill_quantity", "order_status_unknown",
    "cancel_rejected", "cancel_too_late", "stop_attach_failed",
    "target_attach_failed", "bracket_partially_attached", "ghost_position",
    "missing_position", "cash_mismatch", "account_locked", "rate_limited",
    "market_closed", "trading_halt", "symbol_not_tradable",
    "borrow_unavailable", "invalid_tick_size", "invalid_lot_size",
    "broker_maintenance", "wide_spread",
}
CHAOS_SCENARIOS = tuple(sorted(SCENARIOS))


@dataclass
class ChaosResult:
    scenario: str
    status: str
    blocks_new_entries: bool
    incident_id: str | None = None


class FakeBrokerChaosAdapter(BrokerAdapter):
    name = "fake_broker_chaos"
    is_live = False

    def __init__(self, scenario: str = "reject_order"):
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown chaos scenario: {scenario}")
        self.scenario = scenario
        self._account = {"equity": 50000.0, "cash": 50000.0, "buying_power": 50000.0}
        self._orders: dict[str, dict[str, Any]] = {}
        self._fills: list[dict[str, Any]] = []
        self._positions: dict[str, dict[str, Any]] = {}

    def get_account(self) -> dict:
        if self.scenario in {"cash_mismatch", "account_locked"}:
            return {**self._account, "cash": -1.0, "status": self.scenario}
        return dict(self._account)

    def get_positions(self) -> list[dict]:
        if self.scenario == "ghost_position":
            return [{"symbol": "GHOST", "qty": 1, "stop": None}]
        if self.scenario == "missing_position":
            return []
        return list(self._positions.values())

    def get_open_orders(self) -> list[dict]:
        return [o for o in self._orders.values() if o.get("status") in {"accepted", "unknown"}]

    def get_latest_quote(self, symbol: str) -> dict:
        if self.scenario == "wide_spread":
            return {"symbol": symbol, "bid": 99.0, "ask": 105.0, "last": 102.0, "ts_age_seconds": 1}
        if self.scenario in {"market_closed", "trading_halt", "symbol_not_tradable"}:
            return {"symbol": symbol, "bid": None, "ask": None, "tradable": False}
        return {"symbol": symbol, "bid": 99.9, "ask": 100.1, "last": 100.0, "ts_age_seconds": 1}

    def is_market_open(self) -> bool:
        return self.scenario not in {"market_closed", "broker_maintenance"}

    def is_symbol_tradable(self, symbol: str) -> bool:
        return self.scenario not in {"symbol_not_tradable", "trading_halt", "borrow_unavailable"}

    def _place(self, intent: OrderIntent) -> dict:
        cid = intent.client_order_id
        base = {
            "client_order_id": cid,
            "symbol": intent.symbol,
            "side": intent.side,
            "qty": intent.qty,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "scenario": self.scenario,
        }
        if self.scenario == "timeout_before_ack":
            raise BrokerTimeout(self.scenario)
        if self.scenario == "disconnect_before_fill":
            raise BrokerDisconnect(self.scenario)
        if self.scenario in {"account_locked", "rate_limited", "broker_maintenance"}:
            raise BrokerError(self.scenario)
        if self.scenario in {"reject_order", "market_closed", "trading_halt", "symbol_not_tradable", "invalid_tick_size", "invalid_lot_size"}:
            rec = {**base, "status": "rejected", "reason": self.scenario, "filled_qty": 0}
            self._orders[cid] = rec
            return rec
        if self.scenario == "order_status_unknown":
            rec = {**base, "status": "unknown", "filled_qty": 0}
            self._orders[cid] = rec
            return rec

        fill_qty = intent.qty
        fill_price = intent.limit_price or intent.entry or 100.0
        if self.scenario == "partial_fill":
            fill_qty = max(1, int(intent.qty * 0.5))
        if self.scenario == "bad_fill_price":
            fill_price *= 1.25
        if self.scenario == "wide_spread":
            fill_price *= 1.03
        if self.scenario == "missing_fill_price":
            fill_price = None
        if self.scenario == "missing_fill_quantity":
            fill_qty = None

        rec = {**base, "status": "filled", "filled_qty": fill_qty, "avg_price": fill_price}
        if self.scenario == "partial_fill":
            rec["status"] = "partially_filled"
        if self.scenario in {"duplicate_ack", "late_fill", "timeout_after_ack", "disconnect_after_fill"}:
            rec["ack_anomaly"] = self.scenario
        if self.scenario in {"stop_attach_failed", "target_attach_failed", "bracket_partially_attached"}:
            rec["protective_order_attached"] = False
            inc = incident_manager.create_incident(
                severity="critical",
                category="execution",
                symbol=intent.symbol,
                strategy=intent.strategy,
                description=f"{self.scenario}: filled order lacks complete protection",
                evidence={"client_order_id": cid},
                runbook_step="Engage kill switch, attach/close protection manually, reconcile broker state.",
            )
            rec["incident_id"] = inc["incident_id"]
        else:
            rec["protective_order_attached"] = bool(intent.stop_loss)

        self._orders[cid] = rec
        if fill_qty and fill_price:
            fill = {"client_order_id": cid, "symbol": intent.symbol, "qty": fill_qty, "price": fill_price}
            self._fills.append(fill)
            if self.scenario == "duplicate_fill":
                self._fills.append(dict(fill))
            self._positions[intent.symbol] = {
                "symbol": intent.symbol,
                "qty": fill_qty,
                "entry": fill_price,
                "stop": intent.stop_loss,
                "target": intent.take_profit,
            }
        return rec

    def cancel_order(self, client_order_id: str) -> dict:
        if self.scenario == "cancel_rejected":
            return {"status": "rejected", "reason": "cancel_rejected"}
        if self.scenario == "cancel_too_late":
            return {"status": "too_late"}
        self._orders.get(client_order_id, {})["status"] = "cancelled"
        return {"status": "cancelled", "client_order_id": client_order_id}

    def get_order(self, client_order_id: str) -> dict:
        return dict(self._orders.get(client_order_id, {}))

    def list_fills(self) -> list[dict]:
        return list(self._fills)


FakeBrokerChaos = FakeBrokerChaosAdapter


def classify_outcome(outcome: dict) -> str:
    """Reduce a broker outcome to a control decision for stress assertions."""
    status = outcome.get("status")
    if (
        outcome.get("needs_incident")
        or outcome.get("incident_id")
        or status == "unknown"
        or outcome.get("duplicate_fill")
        or outcome.get("avg_price") is None and status in {"filled", "partially_filled"}
        or outcome.get("filled_qty") is None and status in {"filled", "partially_filled"}
    ):
        return "incident"
    if status == "partially_filled":
        return "partial"
    if status in {"accepted", "acknowledged"}:
        return "pending"
    if outcome.get("protective_order_attached") is False:
        return "incident"
    if status == "filled" and outcome.get("avg_price") and outcome.get("filled_qty"):
        return "clean_fill"
    if status == "rejected":
        return "attention"
    return "incident"


def run_scenario(name: str) -> ChaosResult:
    adapter = FakeBrokerChaosAdapter(name)
    from execution.order_manager import OrderManager, Proposal
    proposal = Proposal(
        symbol="NVDA",
        side="buy",
        strategy="CHAOS",
        setup="CHAOS",
        entry=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        confidence=0.7,
        evidence_source="paper",
        quote={
            "bid": 99.9,
            "ask": 100.1,
            "last": 100.0,
            "ts_age_seconds": 1,
            "avg_dollar_volume": 5e8,
            "tradable": True,
        },
    )
    manager = OrderManager(adapter=adapter, mode="paper")
    try:
        result = manager.submit(proposal, human_approved=True)
        resp = result.broker_response or {}
        incident_id = resp.get("incident_id")
        status = str(resp.get("status") or result.rejected_reason or "unknown")
    except BrokerError:
        incident_id = None
        status = "broker_error"
    return ChaosResult(name, status, incident_manager.blocks_new_entries(), incident_id)


if __name__ == "__main__":
    import json
    print(json.dumps([run_scenario(s).__dict__ for s in sorted(SCENARIOS)], indent=2))
