#!/usr/bin/env python3
"""Seconds-level quote gate. The order path calls validate() fail-closed before
any entry. Reconstructed to satisfy tests/test_quote_validator.py and the caller
contract in execution/order_manager.py:121 (reads .ok, .reasons, .spread_bps,
.market_session). Thresholds come from config/risk_policy.yaml execution_risk.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class QuoteCheck:
    ok: bool
    reasons: list = field(default_factory=list)
    spread_bps: float = 0.0
    market_session: str = "unknown"


def _exec_policy() -> dict:
    try:
        from safety import risk_policy
        return dict(risk_policy.load().get("execution_risk", {}) or {})
    except Exception:
        # Fail-closed defaults mirroring config/risk_policy.yaml.
        return {}


def validate(quote: dict, *, intraday: bool = True,
             require_market_open: bool = False) -> QuoteCheck:
    """Validate a quote dict. Fail-closed: missing/invalid fields => not ok.

    Expected quote keys: bid, ask, last, ts_age_seconds, avg_dollar_volume,
    market_session ("regular"/...), tradable.
    """
    q = quote or {}
    pol = _exec_policy()
    reasons: list = []

    bid = q.get("bid")
    ask = q.get("ask")
    session = q.get("market_session") or q.get("session") or "unknown"

    # tradability
    if pol.get("require_symbol_tradable", True) and q.get("tradable") is False:
        reasons.append("asset not tradable")

    # bid/ask presence
    if pol.get("require_quote_bid_ask", True) and (bid is None or ask is None):
        reasons.append("missing bid/ask")

    # spread
    spread_bps = 0.0
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2.0
        if ask < bid:
            reasons.append("crossed quote (ask < bid)")
        spread_bps = (ask - bid) / mid * 10000.0 if mid > 0 else 1e9
        max_spread = float(pol.get("max_spread_bps", 50))
        if spread_bps > max_spread:
            reasons.append(f"spread {spread_bps:.0f}bps > max {max_spread:.0f}bps")

    # staleness
    age = q.get("ts_age_seconds")
    if age is None:
        reasons.append("missing quote timestamp")
    else:
        key = "max_data_age_seconds_intraday" if intraday else "max_data_age_seconds_eod"
        max_age = float(pol.get(key, 300 if intraday else 93600))
        if float(age) > max_age:
            reasons.append(f"stale quote ({age:.0f}s > {max_age:.0f}s)")

    # liquidity
    adv = q.get("avg_dollar_volume")
    if adv is not None:
        min_adv = float(pol.get("min_avg_dollar_volume", 20_000_000))
        if float(adv) < min_adv:
            reasons.append(f"illiquid (avg$vol {adv:.0f} < {min_adv:.0f})")

    # market session
    if require_market_open and session != "regular":
        reasons.append(f"market not in regular session ({session})")

    return QuoteCheck(ok=(len(reasons) == 0), reasons=reasons,
                      spread_bps=round(spread_bps, 2), market_session=session)
