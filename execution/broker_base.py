#!/usr/bin/env python3
"""Broker adapter contract. Adapters are DUMB pipes: they accept a fully-formed,
risk-approved OrderIntent and talk to a venue. They never size, never read
scorecards, never import strategies/agents, never override a risk decision.

Invariants enforced here:
  - submit() accepts ONLY an OrderIntent that is approved_by_risk (else raises).
  - the live adapter refuses to exist/operate unless the live guard passes.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any

from safety.order import OrderIntent


class DisabledLiveTradingError(RuntimeError):
    """Raised whenever a live broker pathway is touched while live is disabled."""


class BrokerError(RuntimeError):
    pass


class BrokerAdapter(ABC):
    """All venue adapters implement this. Read methods + a guarded submit."""

    name = "base"
    is_live = False

    # ---- read-only market/account state ----
    @abstractmethod
    def get_account(self) -> dict: ...
    @abstractmethod
    def get_positions(self) -> list[dict]: ...
    @abstractmethod
    def get_open_orders(self) -> list[dict]: ...
    @abstractmethod
    def get_latest_quote(self, symbol: str) -> dict: ...
    @abstractmethod
    def is_market_open(self) -> bool: ...
    @abstractmethod
    def is_symbol_tradable(self, symbol: str) -> bool: ...

    # ---- the ONLY write entrypoint ----
    def submit(self, intent: OrderIntent) -> dict:
        if not isinstance(intent, OrderIntent):
            raise BrokerError("submit() requires an OrderIntent, not raw fields")
        if not intent.approved_by_risk:
            raise BrokerError("submit() refused: intent.approved_by_risk is False")
        if self.is_live:
            raise DisabledLiveTradingError(
                "Live submit blocked at adapter — live trading is disabled")
        return self._place(intent)

    @abstractmethod
    def _place(self, intent: OrderIntent) -> dict:
        """Venue-specific placement. Receives a validated, approved intent."""

    # adapters must NOT accept raw symbol/side/qty submissions
    def submit_raw(self, *a: Any, **k: Any):  # pragma: no cover - contract guard
        raise BrokerError("raw order submission is forbidden; use submit(OrderIntent)")

    # ---- optional venue ops (override where supported) ----
    def cancel_order(self, client_order_id: str) -> dict:
        raise BrokerError("cancel_order not supported by this adapter")
    def cancel_all(self) -> dict:
        raise BrokerError("cancel_all not supported by this adapter")
    def close_position(self, symbol: str) -> dict:
        raise BrokerError("close_position not supported by this adapter")
    def close_all(self) -> dict:
        raise BrokerError("close_all not supported by this adapter")
    def get_order(self, client_order_id: str) -> dict:
        raise BrokerError("get_order not supported by this adapter")
    def list_fills(self) -> list[dict]:
        raise BrokerError("list_fills not supported by this adapter")
    def get_clock(self) -> dict:
        return {"is_open": self.is_market_open()}
    def get_asset(self, symbol: str) -> dict:
        return {"symbol": symbol, "tradable": self.is_symbol_tradable(symbol)}


class NullBrokerAdapter(BrokerAdapter):
    """No-op adapter for tests and dry-runs. Records intents, places nothing real."""

    name = "null"
    is_live = False

    def __init__(self):
        self.placed: list[OrderIntent] = []
        self._account = {"equity": 50000.0, "cash": 50000.0, "buying_power": 50000.0}

    def get_account(self) -> dict:
        return dict(self._account)

    def get_positions(self) -> list[dict]:
        return []

    def get_open_orders(self) -> list[dict]:
        return []

    def get_latest_quote(self, symbol: str) -> dict:
        return {"symbol": symbol, "bid": None, "ask": None, "ts": None}

    def is_market_open(self) -> bool:
        return True

    def is_symbol_tradable(self, symbol: str) -> bool:
        return True

    def _place(self, intent: OrderIntent) -> dict:
        self.placed.append(intent)
        return {"broker": "null", "client_order_id": intent.client_order_id,
                "status": "accepted", "filled_qty": 0}


class DisabledLiveAdapter(BrokerAdapter):
    """Placeholder for a real live venue. Present but inert — any touch raises."""

    name = "alpaca_live"
    is_live = True

    def __init__(self, env: dict | None = None):
        raise DisabledLiveTradingError(
            "AlpacaLiveAdapter is disabled. Live trading requires a future, "
            "explicitly-approved build with reconciliation + forward paper evidence.")

    def get_account(self): raise DisabledLiveTradingError("live disabled")
    def get_positions(self): raise DisabledLiveTradingError("live disabled")
    def get_open_orders(self): raise DisabledLiveTradingError("live disabled")
    def get_latest_quote(self, symbol): raise DisabledLiveTradingError("live disabled")
    def is_market_open(self): raise DisabledLiveTradingError("live disabled")
    def is_symbol_tradable(self, symbol): raise DisabledLiveTradingError("live disabled")
    def _place(self, intent): raise DisabledLiveTradingError("live disabled")
