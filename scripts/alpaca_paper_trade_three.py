#!/usr/bin/env python3
"""Submit three TradingBrain-selected US stocks to Alpaca paper trading.

This command is paper-only. It uses OrderManager as the single order path, the
AlpacaPaperAdapter as the venue pipe, and writes a report for audit. By default
it uses the latest quick 3-stock backtest scorer output.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execution.alpaca_paper_adapter import AlpacaPaperAdapter
from execution.order_manager import OrderManager, Proposal
from paths import REPORTS_DIR


OUT = REPORTS_DIR / "alpaca-paper-trade-three-latest.json"
DEFAULT_SYMBOLS = ["AAOI", "MRVL", "INTC"]


def _json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {} if default is None else default


def _symbols_from_report() -> list[str]:
    out: list[str] = []
    narrative = _json(REPORTS_DIR / "event-narrative-intelligence-latest.json", {})
    narrative_blocked = {
        str(row.get("ticker", "")).upper()
        for row in (narrative.get("events") or [])
        if row.get("ticker") and row.get("final_signal") in {"watchlist_wait_for_pullback", "blocked_unverified"}
    }
    narrative_symbols = narrative.get("paper_candidate_top3") or []
    if isinstance(narrative_symbols, list):
        for symbol in narrative_symbols:
            s = str(symbol).upper().strip()
            if s and s not in narrative_blocked and s not in out:
                out.append(s)

    skill_lab = _json(REPORTS_DIR / "paper-skill-lab-latest.json", {})
    skill_symbols = skill_lab.get("ensemble_top3") or ((skill_lab.get("best_skill") or {}).get("current_top3") or [])
    if isinstance(skill_symbols, list) and len(skill_symbols) >= 3:
        for symbol in skill_symbols:
            s = str(symbol).upper().strip()
            if s and s not in narrative_blocked and s not in out:
                out.append(s)
        if len(out) >= 3:
            return out[:3]

    report = _json(REPORTS_DIR / "quick-3stock-backtest-latest.json", {})
    symbols = (
        (report.get("best_detail") or {}).get("current_top3_by_same_score_as_of_latest_date")
        or ((report.get("best") or {}).get("current_top3_by_same_score_as_of_latest_date"))
    )
    if not isinstance(symbols, list) or len(symbols) < 3:
        symbols = list(DEFAULT_SYMBOLS)
    for symbol in symbols:
        s = str(symbol).upper().strip()
        if s and s not in narrative_blocked and s not in out:
            out.append(s)
    for symbol in DEFAULT_SYMBOLS:
        s = str(symbol).upper().strip()
        if s and s not in narrative_blocked and s not in out:
            out.append(s)
    return out[:3]


def _position_rows(adapter: AlpacaPaperAdapter) -> list[dict[str, Any]]:
    rows = []
    for p in adapter.get_positions():
        symbol = str(p.get("symbol", "")).upper()
        qty = float(p.get("qty") or 0)
        entry = float(p.get("avg_entry_price") or p.get("cost_basis") or 0)
        if entry > 0 and abs(qty) > 0 and p.get("cost_basis") is not None and p.get("avg_entry_price") is None:
            entry = float(p.get("cost_basis")) / abs(qty)
        last = float(p.get("current_price") or entry or 0)
        rows.append(
            {
                "symbol": symbol,
                "qty": qty,
                "entry": entry,
                "last": last,
                "value": abs(qty) * last,
                "risk_pct": 0.0,
            }
        )
    return rows


def _round_price(value: float) -> float:
    return round(float(value), 2)


def _plan_from_quote(symbol: str, quote: dict[str, Any]) -> dict[str, Any]:
    ask = float(quote["ask"])
    entry = _round_price(ask * 1.002)
    stop = _round_price(entry * 0.97)
    target = _round_price(entry * 1.06)
    return {
        "symbol": symbol,
        "entry": entry,
        "stop_loss": stop,
        "take_profit": target,
        "reward_to_risk": round((target - entry) / max(entry - stop, 0.01), 2),
        "confidence": 0.60,
        "strategy": "QUICK_3STOCK_MOMO",
        "setup": "TOP3_MOMENTUM_42D",
    }


def run(*, symbols: list[str] | None = None, execute: bool = False) -> dict[str, Any]:
    os.environ.setdefault("TB_MODE", "paper")
    adapter = AlpacaPaperAdapter()
    account = adapter.get_account()
    clock = adapter.get_clock()
    positions = _position_rows(adapter)
    open_orders = adapter.get_open_orders()
    equity = float(account.get("equity") or 0)
    cash = float(account.get("cash") or 0)
    gross_exposure = sum(float(p.get("value") or 0) for p in positions)
    preflight_blockers: list[str] = []
    if account.get("trading_blocked") or account.get("account_blocked"):
        preflight_blockers.append("Alpaca account is trading/account blocked")
    if cash < 0:
        preflight_blockers.append(f"cash is negative (${cash:,.2f}); new entries blocked")
    if open_orders:
        preflight_blockers.append(f"{len(open_orders)} open broker order(s) exist; reconcile/cancel before new entries")
    if equity > 0 and gross_exposure / equity > 1.0:
        preflight_blockers.append(
            f"gross exposure is {gross_exposure / equity * 100:.1f}% of equity; new entries blocked"
        )
    held = {p["symbol"] for p in positions}
    open_order_symbols = {str(o.get("symbol", "")).upper() for o in open_orders}
    symbols = [s.upper() for s in (symbols or _symbols_from_report())][:3]
    manager = OrderManager(adapter=adapter, mode="paper")

    results = []
    if not clock.get("is_open"):
        execute = False
        preflight_blockers.append("market is not open")
    if preflight_blockers:
        execute = False

    for symbol in symbols:
        row: dict[str, Any] = {"symbol": symbol, "submitted": False}
        if preflight_blockers:
            row.update({"status": "blocked_preflight", "reason": "; ".join(preflight_blockers)})
            results.append(row)
            continue
        if symbol in held:
            row.update({"status": "skipped", "reason": "already held in Alpaca paper account"})
            results.append(row)
            continue
        if symbol in open_order_symbols:
            row.update({"status": "skipped", "reason": "open Alpaca paper order already exists"})
            results.append(row)
            continue
        try:
            quote = adapter.get_latest_quote(symbol)
            plan = _plan_from_quote(symbol, quote)
            proposal = Proposal(
                symbol=symbol,
                side="buy",
                strategy=plan["strategy"],
                setup=plan["setup"],
                entry=plan["entry"],
                stop_loss=plan["stop_loss"],
                take_profit=plan["take_profit"],
                confidence=plan["confidence"],
                evidence_source="paper_forward_research",
                source_agent="quick_3stock_backtest",
                thesis="3-stock momentum paper test from quick historical replay; paper-only.",
                quote=quote,
                current_positions=positions,
            )
            if execute:
                result = manager.submit(proposal, human_approved=True)
                row.update(
                    {
                        "status": "submitted" if result.submitted else "rejected",
                        "submitted": bool(result.submitted),
                        "approved": bool(result.approved),
                        "rejected_reason": result.rejected_reason,
                        "client_order_id": result.client_order_id,
                        "risk_decision": result.risk_decision,
                        "broker_response": result.broker_response,
                        "plan": plan,
                        "quote": {k: quote.get(k) for k in ["bid", "ask", "last", "ts_age_seconds", "tradable"]},
                    }
                )
            else:
                row.update(
                    {
                        "status": "planned",
                        "submitted": False,
                        "reason": "dry run; pass --execute to submit paper orders",
                        "plan": plan,
                        "quote": {k: quote.get(k) for k in ["bid", "ask", "last", "ts_age_seconds", "tradable"]},
                    }
                )
        except Exception as exc:
            row.update({"status": "error", "reason": str(exc)})
        results.append(row)

    report = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "mode": "paper",
        "execute": execute,
        "paper_only": True,
        "alpaca_account": {
            "status": account.get("status"),
            "equity": account.get("equity"),
            "cash": account.get("cash"),
            "buying_power": account.get("buying_power"),
            "trading_blocked": account.get("trading_blocked"),
        },
        "clock": clock,
        "positions_before": positions,
        "preflight_blockers": preflight_blockers,
        "open_orders_before": [
            {
                "id": o.get("id"),
                "symbol": o.get("symbol"),
                "status": o.get("status"),
                "client_order_id": o.get("client_order_id"),
            }
            for o in open_orders
        ],
        "symbols": symbols,
        "results": results,
        "orders_submitted": sum(1 for r in results if r.get("submitted")),
        "methodology_caveat": (
            "Paper trading only. This is not live trading and not financial advice. "
            "Orders are limit bracket orders with stop-loss and take-profit."
        ),
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true", help="Actually submit Alpaca paper orders")
    ap.add_argument("--symbols", nargs="*", help="Override the 3 symbols")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run(symbols=args.symbols, execute=args.execute)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        print(f"Alpaca paper 3-stock run: submitted {report['orders_submitted']} order(s).")
        print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
