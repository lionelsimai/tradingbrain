#!/usr/bin/env python3
"""Stop/target policy. Every entry must have a stop; a filled entry without an
active stop is an INCIDENT. Live placement stays disabled until this is fully
tested against a sandbox.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import risk_policy


def require_protective(intent) -> list[str]:
    """Return reasons the order must be rejected for missing protection."""
    pol = risk_policy.load()["execution_risk"]
    problems = []
    if pol.get("require_stop_loss", True):
        if intent.stop_loss is None or intent.stop_loss <= 0:
            problems.append("missing stop loss")
        elif intent.side == "buy" and intent.stop_loss >= intent.entry_reference_price_or(intent):
            problems.append("long stop must be below entry")
    if pol.get("require_target_or_trailing_policy", True):
        if intent.take_profit is None and not getattr(intent, "trailing", None):
            problems.append("missing target or trailing-exit policy")
    return problems


def attach(adapter, intent) -> dict:
    """Attempt to attach stop+target after a fill. Returns status; a failure here
    is an incident the caller must escalate."""
    result = {"stop_attached": False, "target_attached": False, "incident": False, "reasons": []}
    if intent.stop_loss:
        try:
            # paper adapter carries stop on the position already (bracket); mark attached
            pos = {p["symbol"]: p for p in adapter.get_positions()}.get(intent.symbol)
            result["stop_attached"] = bool(pos and pos.get("stop"))
        except Exception as e:
            result["reasons"].append(f"stop attach failed: {e}")
    if intent.take_profit:
        try:
            pos = {p["symbol"]: p for p in adapter.get_positions()}.get(intent.symbol)
            result["target_attached"] = bool(pos and pos.get("target"))
        except Exception as e:
            result["reasons"].append(f"target attach failed: {e}")
    if intent.stop_loss and not result["stop_attached"]:
        result["incident"] = True
        result["reasons"].append("filled entry without active stop")
    return result


def verify_after_fill(adapter, intent, resp: dict | None = None) -> dict:
    """VERIFY (not infer) that a protective stop exists at the broker after a
    fill. FIX-2 (P0-4): the prior code inferred "attached" from a status string;
    here a stop is verified iff EITHER an open stop ORDER exists for the symbol OR
    the broker position carries a stop level. Fail-closed: read errors => not
    verified. Returns {verified, reasons, checks}.
    """
    if not getattr(intent, "stop_loss", None):
        return {"verified": True, "reasons": [], "checks": {"no_stop_required": True}}
    sym = str(intent.symbol).upper()
    reasons: list[str] = []

    stop_order = False
    try:
        for o in (adapter.get_open_orders() or []):
            if str(o.get("symbol", "")).upper() != sym:
                continue
            otype = str(o.get("type") or o.get("order_type") or "").lower()
            if ("stop" in otype or o.get("stop_price") is not None
                    or o.get("stop") is not None or o.get("stop_loss") is not None):
                stop_order = True
                break
    except Exception as e:  # fail-closed: an unreadable broker is NOT proof of a stop
        reasons.append(f"open-order read failed: {type(e).__name__}")

    pos_stop = False
    try:
        pos = next((p for p in (adapter.get_positions() or [])
                    if str(p.get("symbol", "")).upper() == sym), None)
        pos_stop = bool(pos and pos.get("stop"))
    except Exception as e:
        reasons.append(f"position read failed: {type(e).__name__}")

    verified = bool(stop_order or pos_stop)
    if not verified:
        reasons.append("filled entry has NO broker-verified protective stop "
                       "(no stop order, no position stop)")
    return {"verified": verified, "reasons": reasons,
            "checks": {"stop_order": stop_order, "position_stop": pos_stop}}


# small helper so require_protective can read an entry ref off the intent
def _entry_ref(intent):
    return getattr(intent, "entry_reference_price", None) or getattr(intent, "limit_price", None) or 0.0


# monkey-friendly accessor used above
def _patch():
    from safety.order import Order
    if not hasattr(Order, "entry_reference_price_or"):
        Order.entry_reference_price_or = lambda self, _i=None: (
            getattr(self, "entry_reference_price", None) or self.limit_price or 1e9)


_patch()


if __name__ == "__main__":
    from safety.order import Order
    o = Order(symbol="NVDA", side="buy", strategy="X", client_order_id="c1",
              qty=10, limit_price=212, stop_loss=None, take_profit=236)
    print("missing-stop problems:", require_protective(o))
