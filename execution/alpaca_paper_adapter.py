#!/usr/bin/env python3
"""Alpaca paper-trading adapter.

This is a paper-only BrokerAdapter. It refuses live endpoints, accepts only
risk-approved OrderIntent objects through the base BrokerAdapter.submit()
contract, and places limit bracket orders with an attached stop and target.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from execution.broker_base import BrokerAdapter, BrokerError
from execution import protective_orders
from safety.order import OrderIntent


DEFAULT_BASE = "https://paper-api.alpaca.markets/v2"
DEFAULT_DATA_BASE = "https://data.alpaca.markets/v2"


class AlpacaPaperAdapter(BrokerAdapter):
    """Paper-only Alpaca adapter. Never use this for live endpoints."""

    name = "alpaca_paper"
    is_live = False

    def __init__(
        self,
        *,
        key_id: str | None = None,
        secret_key: str | None = None,
        base_url: str | None = None,
        data_url: str | None = None,
        data_feed: str | None = None,
        session: Any | None = None,
    ):
        self.key_id = key_id if key_id is not None else os.environ.get("APCA_API_KEY_ID")
        self.secret_key = secret_key if secret_key is not None else os.environ.get("APCA_API_SECRET_KEY")
        self.base_url = self.validate_base_url(base_url or os.environ.get("APCA_API_BASE_URL", DEFAULT_BASE))
        self.data_url = self.validate_data_url(data_url or os.environ.get("APCA_DATA_BASE_URL", DEFAULT_DATA_BASE))
        self.data_feed = data_feed or os.environ.get("APCA_DATA_FEED", "iex")
        self.session = session or requests.Session()
        if not self.key_id or not self.secret_key:
            raise BrokerError("Alpaca paper adapter requires APCA_API_KEY_ID and APCA_API_SECRET_KEY")

    @staticmethod
    def validate_base_url(base_url: str) -> str:
        normalized = str(base_url).rstrip("/")
        if normalized != DEFAULT_BASE:
            raise BrokerError(f"AlpacaPaperAdapter refuses non-paper endpoint: {normalized}")
        return normalized

    @staticmethod
    def validate_data_url(data_url: str) -> str:
        normalized = str(data_url).rstrip("/")
        if normalized != DEFAULT_DATA_BASE:
            raise BrokerError(f"AlpacaPaperAdapter refuses untrusted data endpoint: {normalized}")
        return normalized

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.key_id or "",
            "APCA-API-SECRET-KEY": self.secret_key or "",
            "Content-Type": "application/json",
        }

    def _url(self, path: str, *, data: bool = False) -> str:
        suffix = "/" + path.lstrip("/")
        if suffix.startswith("/v2/"):
            suffix = suffix[3:]
        return f"{self.data_url if data else self.base_url}{suffix}"

    def _request(self, method: str, path: str, *, data_api: bool = False, **kwargs):
        method = method.upper()
        if method in {"POST", "PATCH", "DELETE"} and self.base_url != DEFAULT_BASE:
            raise BrokerError("Alpaca paper write refused: endpoint is not paper")
        response = self.session.request(
            method,
            self._url(path, data=data_api),
            headers=self._headers(),
            timeout=15,
            **kwargs,
        )
        try:
            response.raise_for_status()
        except Exception as exc:
            text = getattr(response, "text", "")
            raise BrokerError(f"Alpaca paper {method} {path} failed: {exc}; {text[:240]}") from exc
        return response.json() if getattr(response, "text", "") else {}

    def get_account(self) -> dict:
        return self._request("GET", "/account")

    def get_positions(self) -> list[dict]:
        return list(self._request("GET", "/positions") or [])

    def get_open_orders(self) -> list[dict]:
        return list(self._request("GET", "/orders", params={"status": "open", "limit": 100}) or [])

    def get_latest_quote(self, symbol: str) -> dict:
        symbol = symbol.upper()
        params = {"feed": self.data_feed} if self.data_feed else None
        raw = self._request("GET", f"/stocks/{symbol}/quotes/latest", data_api=True, params=params)
        quote = raw.get("quote") or raw
        bid = quote.get("bp")
        ask = quote.get("ap")
        ts = quote.get("t")
        age = None
        if ts:
            try:
                parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
                age = max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
            except Exception:
                age = None
        last = None
        if bid is not None and ask is not None:
            last = (float(bid) + float(ask)) / 2.0
        return {
            "symbol": symbol,
            "bid": float(bid) if bid is not None else None,
            "ask": float(ask) if ask is not None else None,
            "last": last,
            "ts_age_seconds": age,
            "avg_dollar_volume": None,
            "tradable": self.is_symbol_tradable(symbol),
            "raw": raw,
        }

    def is_market_open(self) -> bool:
        return bool((self._request("GET", "/clock") or {}).get("is_open"))

    def is_symbol_tradable(self, symbol: str) -> bool:
        try:
            asset = self._request("GET", f"/assets/{symbol.upper()}")
        except BrokerError:
            return False
        return bool(asset.get("tradable")) and str(asset.get("status", "active")).lower() == "active"

    def get_clock(self) -> dict:
        return self._request("GET", "/clock")

    def get_asset(self, symbol: str) -> dict:
        return self._request("GET", f"/assets/{symbol.upper()}")

    def _place(self, intent: OrderIntent) -> dict:
        if str(intent.mode).lower() != "paper":
            return {
                "status": "rejected",
                "reason": f"AlpacaPaperAdapter only accepts mode=paper, got {intent.mode}",
                "client_order_id": intent.client_order_id,
            }
        protective = protective_orders.require_protective(intent)
        if protective:
            return {
                "status": "rejected",
                "reason": "; ".join(protective),
                "client_order_id": intent.client_order_id,
            }
        if intent.order_type != "limit":
            return {
                "status": "rejected",
                "reason": "paper adapter only places limit orders",
                "client_order_id": intent.client_order_id,
            }
        for order in self.get_open_orders():
            if order.get("client_order_id") == intent.client_order_id:
                out = dict(order)
                out["status"] = out.get("status") or "accepted"
                out["duplicate_existing_order"] = True
                return out

        payload = {
            "symbol": intent.symbol.upper(),
            "qty": str(int(intent.qty)),
            "side": intent.side.lower(),
            "type": "limit",
            "time_in_force": intent.time_in_force or "day",
            "limit_price": str(round(float(intent.limit_price or intent.entry or 0), 2)),
            "client_order_id": intent.client_order_id,
            "order_class": "bracket",
            "take_profit": {"limit_price": str(round(float(intent.take_profit), 2))},
            "stop_loss": {"stop_price": str(round(float(intent.stop_loss), 2))},
        }
        response = self._request("POST", "/orders", json=payload)
        response.setdefault("client_order_id", intent.client_order_id)
        response.setdefault("status", "accepted")
        return response
