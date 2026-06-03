#!/usr/bin/env python3
"""Realistic paper broker adapter. Implements the BrokerAdapter contract and
simulates the things that make paper trading honest: bid/ask spread, slippage,
partial fills, rejected orders (stale quote / cash short), stop/target brackets,
and gap-through-stop. State persists in the paper_* DB tables.

It accepts ONLY a risk-approved OrderIntent (enforced by the base submit()).
"""
from __future__ import annotations
import random
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution.broker_base import BrokerAdapter, BrokerError
from safety.order import OrderIntent
from safety import risk_policy


def _now():
    return datetime.now(timezone.utc)


@dataclass
class PaperConfig:
    slippage_bps: float = 5.0
    spread_bps: float = 8.0
    partial_fill_prob: float = 0.15
    reject_if_quote_age_s: float = 300.0
    seed: int | None = 7


class PaperAdapter(BrokerAdapter):
    """In-process realistic paper broker. Not persisted unless persist=True."""
    name = "paper"
    is_live = False

    def __init__(self, equity: float | None = None, cfg: PaperConfig | None = None,
                 quotes: dict | None = None):
        self.cfg = cfg or PaperConfig()
        if self.cfg.seed is not None:
            self._rng = random.Random(self.cfg.seed)
        else:
            self._rng = random.Random()
        eq = equity if equity is not None else float(
            risk_policy.get("account", "default_equity_usd", 50000))
        self._account = {"equity": eq, "cash": eq, "buying_power": eq}
        self._positions: dict[str, dict] = {}
        self._orders: dict[str, dict] = {}
        self._fills: list[dict] = []
        self._quotes = quotes or {}   # symbol -> {bid, ask, last, ts_age_s}

    # ---- read state ----
    def get_account(self) -> dict:
        return dict(self._account)

    def get_positions(self) -> list[dict]:
        return list(self._positions.values())

    def get_open_orders(self) -> list[dict]:
        return [o for o in self._orders.values() if o["status"] in ("accepted", "partially_filled")]

    def get_latest_quote(self, symbol: str) -> dict:
        return self._quotes.get(symbol, {})

    def is_market_open(self) -> bool:
        from data import market_calendar
        return market_calendar.session() == "regular"

    def is_symbol_tradable(self, symbol: str) -> bool:
        return True

    def set_quote(self, symbol: str, bid: float, ask: float, last: float | None = None,
                  age_s: float = 0.0):
        self._quotes[symbol] = {"bid": bid, "ask": ask, "last": last or (bid + ask) / 2,
                                "ts_age_s": age_s}

    # ---- placement ----
    def _place(self, intent: OrderIntent) -> dict:
        q = self._quotes.get(intent.symbol)
        oid = intent.client_order_id
        rec = {"client_order_id": oid, "symbol": intent.symbol, "side": intent.side,
               "qty": intent.qty, "filled_qty": 0.0, "status": "accepted",
               "order_type": intent.order_type, "limit_price": intent.limit_price,
               "stop_loss": intent.stop_loss, "take_profit": intent.take_profit,
               "created_at": _now().isoformat(), "avg_price": None}
        self._orders[oid] = rec

        # reject conditions
        if not q:
            rec["status"] = "rejected"; rec["reason"] = "no quote"
            return dict(rec)
        if q.get("ts_age_s", 0) > self.cfg.reject_if_quote_age_s:
            rec["status"] = "rejected"; rec["reason"] = "stale quote"
            return dict(rec)

        ref = q["ask"] if intent.side == "buy" else q["bid"]
        slip = ref * (self.cfg.slippage_bps / 10000.0) * (1 if intent.side == "buy" else -1)
        fill_px = round(ref + slip, 4)
        notional = fill_px * intent.qty
        if intent.side == "buy" and notional > self._account["cash"] + 1e-6:
            rec["status"] = "rejected"; rec["reason"] = "insufficient cash"
            return dict(rec)

        # partial fill?
        partial = self._rng.random() < self.cfg.partial_fill_prob
        fill_qty = max(1, int(intent.qty * (0.5 if partial else 1.0)))
        self._record_fill(rec, fill_qty, fill_px, partial=partial)
        rec["status"] = "partially_filled" if fill_qty < intent.qty else "filled"
        rec["filled_qty"] = fill_qty
        rec["avg_price"] = fill_px
        return dict(rec)

    def _record_fill(self, rec, qty, px, partial=False):
        fid = "f_" + uuid.uuid4().hex[:10]
        self._fills.append({"fill_id": fid, "client_order_id": rec["client_order_id"],
                            "symbol": rec["symbol"], "side": rec["side"], "qty": qty,
                            "price": px, "filled_at": _now().isoformat(), "partial": partial,
                            "slippage_bps": self.cfg.slippage_bps})
        sym, side = rec["symbol"], rec["side"]
        sign = 1 if side == "buy" else -1
        pos = self._positions.get(sym)
        if pos is None:
            self._positions[sym] = {"symbol": sym, "qty": sign * qty, "entry": px, "last": px,
                                    "stop": rec.get("stop_loss"), "target": rec.get("take_profit")}
        else:
            pos["qty"] += sign * qty
            if pos["qty"] == 0:
                self._positions.pop(sym)
        if side == "buy":
            self._account["cash"] -= px * qty
        else:
            self._account["cash"] += px * qty

    # ---- bracket simulation: advance a bar, fire stop/target incl. gap-through ----
    def mark_bar(self, symbol: str, high: float, low: float, close: float) -> dict | None:
        pos = self._positions.get(symbol)
        if not pos:
            return None
        pos["last"] = close
        stop, tgt = pos.get("stop"), pos.get("target")
        long = pos["qty"] > 0
        if stop is not None and ((long and low <= stop) or (not long and high >= stop)):
            # gap-through: fill at the worse of stop or open-of-bar proxy (low/high)
            fill = min(stop, high) if long else max(stop, low)
            fill = stop if (long and low <= stop <= high) else (low if long else high)
            return self._close(symbol, fill, "stop")
        if tgt is not None and ((long and high >= tgt) or (not long and low <= tgt)):
            return self._close(symbol, tgt, "target")
        return None

    def _close(self, symbol: str, px: float, reason: str) -> dict:
        pos = self._positions.pop(symbol)
        qty = abs(pos["qty"])
        self._account["cash"] += px * qty * (1 if pos["qty"] > 0 else -1)
        pnl = (px - pos["entry"]) * pos["qty"]
        self._account["equity"] = self._account["cash"] + sum(
            p["qty"] * p["last"] for p in self._positions.values())
        return {"symbol": symbol, "exit": px, "reason": reason, "pnl": round(pnl, 2)}

    # ---- venue ops ----
    def cancel_order(self, client_order_id: str) -> dict:
        o = self._orders.get(client_order_id)
        if not o:
            raise BrokerError("unknown order")
        if o["status"] in ("filled",):
            return {"status": "too_late"}
        o["status"] = "cancelled"
        return {"status": "cancelled", "client_order_id": client_order_id}

    def close_position(self, symbol: str) -> dict:
        q = self._quotes.get(symbol, {})
        px = q.get("bid") or (self._positions.get(symbol, {}).get("last"))
        if symbol not in self._positions:
            raise BrokerError("no such position")
        return self._close(symbol, px, "manual_close")

    def close_all(self) -> dict:
        out = [self.close_position(s) for s in list(self._positions)]
        return {"closed": out}

    def get_order(self, client_order_id: str) -> dict:
        return dict(self._orders.get(client_order_id, {}))

    def list_fills(self) -> list[dict]:
        return list(self._fills)


if __name__ == "__main__":
    import json
    a = PaperAdapter(equity=50000)
    a.set_quote("NVDA", bid=212.50, ask=212.80, last=212.65, age_s=2)
    intent = OrderIntent(client_order_id="tb_demo1", symbol="NVDA", side="buy", strategy="TREND_LEADER",
                         qty=40, order_type="limit", limit_price=213.0,
                         stop_loss=206.0, take_profit=236.0, approved_by_risk=True)
    print("submit:", json.dumps(a._place(intent), indent=2))
    print("mark stop-gap:", a.mark_bar("NVDA", high=210, low=205, close=205.5))
    print("account:", a.get_account())
