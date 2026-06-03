#!/usr/bin/env python3
"""Gated paper-trading entrypoint. Every candidate routes through the ONE order
path (OrderManager) into the realistic PaperAdapter. This is the Section-13
"paper order uses order_manager" reference flow.

Reads candidates from reports/desk-signals.json (or swing-setups.json) and
processes the top buys. Quotes are synthesized from entry refs for the dry-run.

Usage: python3 -m scripts.paper_trade [--limit N]
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import REPORTS_DIR
from execution.order_manager import OrderManager, Proposal
from execution.paper_adapter import PaperAdapter
from data import market_calendar


def _candidates(limit: int) -> list[dict]:
    for fn in ("desk-signals.json", "swing-setups.json"):
        f = REPORTS_DIR / fn
        if not f.exists():
            continue
        data = json.loads(f.read_text())
        rows = data.get("buys") or data.get("setups") or data.get("candidates") or []
        out = []
        for r in rows[:limit]:
            entry = r.get("entry") or r.get("price")
            stop = r.get("stop") or r.get("stop_loss")
            if not entry or not stop:
                continue
            out.append({"symbol": r.get("ticker") or r.get("symbol"),
                        "strategy": r.get("setup", "UNKNOWN"),
                        "entry": float(entry), "stop": float(stop),
                        "target": float(r.get("t1") or r.get("target") or entry * 1.1),
                        "confidence": float(r.get("confidence", 0.65))})
        if out:
            return out
    return []


def main():
    limit = 5
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    adapter = PaperAdapter()
    om = OrderManager(adapter=adapter, mode="paper")  # OM is the ONLY thing that places
    results = []
    for c in _candidates(limit):
        adapter.set_quote(c["symbol"], bid=c["entry"] * 0.999, ask=c["entry"] * 1.001,
                          last=c["entry"], age_s=2)
        prop = Proposal(symbol=c["symbol"], side="buy", strategy=c["strategy"],
                        setup=c["strategy"], entry=c["entry"], stop_loss=c["stop"],
                        take_profit=c["target"], confidence=c["confidence"],
                        quote={"bid": c["entry"] * 0.999, "ask": c["entry"] * 1.001,
                               "last": c["entry"], "ts_age_seconds": 2,
                               "avg_dollar_volume": 5e8, "tradable": True},
                        current_positions=[p for p in adapter.get_positions()])
        res = om.submit(prop, human_approved=True)
        results.append({"symbol": c["symbol"], "approved": res.approved,
                        "reason": res.rejected_reason, "fill": res.broker_response})
    print(json.dumps({"mode": "paper", "processed": len(results), "results": results,
                      "session": market_calendar.session()}, indent=2, default=str))


if __name__ == "__main__":
    main()
