#!/usr/bin/env python3
"""Order schema + deterministic idempotency keys + a small state machine.

The idempotency key is derived from the normalized signal identity so that the
SAME signal on the SAME day can never create two live orders, even if the
pipeline runs twice. Execution layers must refuse to submit an order whose
client_order_id already exists.
"""
from __future__ import annotations
import hashlib
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, timezone
from typing import Optional

# Order lifecycle states — MUST match execution/order_lifecycle.TRANSITIONS keys.
STATES = ("proposed", "pending_human_review", "approved", "rejected_pretrade",
          "submitted", "acknowledged", "rejected_by_broker", "partially_filled",
          "filled", "stop_pending", "stop_active", "target_pending", "target_active",
          "protective_order_failed", "closing", "closed", "reconciled",
          "cancelled", "incident")


def _key_part(value: str | None) -> str:
    return str(value or "").strip().upper()


def idempotency_key(symbol: str, side: str, strategy: str,
                    trade_date: Optional[str] = None, *,
                    setup: Optional[str] = None,
                    mode: Optional[str] = None,
                    signal_hash: Optional[str] = None) -> str:
    """Deterministic client order id. Same signal identity -> same key."""
    d = trade_date or date.today().isoformat()
    parts = [d, _key_part(symbol), str(side or "").strip().lower(), _key_part(strategy)]
    if setup is not None:
        parts.append(_key_part(setup))
    if mode is not None:
        parts.append(str(mode or "").strip().lower())
    if signal_hash is not None:
        parts.append(str(signal_hash or "").strip().lower())
    raw = "|".join(parts)
    return "tb_" + hashlib.sha256(raw.encode()).hexdigest()[:20]


@dataclass
class Order:
    symbol: str
    side: str                      # "buy" | "sell"
    strategy: str
    setup: Optional[str] = None
    qty: int = 0
    order_type: str = "market"     # market | limit | stop | stop_limit
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "day"
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    state: str = "proposed"
    client_order_id: str = ""
    broker_order_id: Optional[str] = None
    filled_qty: int = 0
    avg_fill_price: Optional[float] = None
    reject_reason: Optional[str] = None
    mode: str = "paper"
    broker: str = "null"
    evidence_source: Optional[str] = None
    signal_hash: Optional[str] = None
    policy_version: Optional[str] = None
    proposal_id: Optional[str] = None
    approved_by_risk: bool = False
    approved_by_human: bool = False
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self):
        if not self.client_order_id:
            self.client_order_id = idempotency_key(self.symbol, self.side, self.strategy,
                                                   setup=self.setup, mode=self.mode,
                                                   signal_hash=self.signal_hash)
        self.symbol = self.symbol.upper()
        self.side = self.side.lower()

    def to_dict(self) -> dict:
        return asdict(self)


OrderIntent = Order


# The execution layer refers to an approved order as an "intent".
OrderIntent = Order


if __name__ == "__main__":
    import json
    o = Order(symbol="nvda", side="buy", strategy="TREND_LEADER", qty=10,
              entry=200.0, stop_loss=190.0, take_profit=230.0, confidence=0.7)
    print(json.dumps(o.to_dict(), indent=2))
    # idempotency: same signal -> same id
    assert Order(symbol="NVDA", side="buy", strategy="TREND_LEADER").client_order_id == o.client_order_id
    print("idempotency OK:", o.client_order_id)
