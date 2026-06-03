#!/usr/bin/env python3
"""THE single order path. Nothing else may place an order.

Pipeline (every step journaled as an event; any failure -> rejection + event):
  proposal -> config_guard -> kill_switch -> quote_validator -> portfolio/risk_gate
           -> human-review gate -> idempotency -> adapter.submit -> fill events

The AI proposes a SignalCandidate/OrderProposal; OrderManager decides and places.
Strategies/agents never call adapters or this submit() with raw fields.
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from typing import Optional

from safety import config_guard, kill_switch, risk_gate, risk_policy
from safety.order import Order, idempotency_key
from safety import trade_journal
from data import quote_validator
from journal import event_store
from execution import order_lifecycle
from execution.broker_base import BrokerAdapter, NullBrokerAdapter


@dataclass
class Proposal:
    symbol: str
    side: str
    strategy: str
    setup: str
    entry: float
    stop_loss: float
    take_profit: Optional[float] = None
    confidence: Optional[float] = None
    evidence_source: str = "backtest"
    source_agent: str = "signal_engine"
    signal_hash: Optional[str] = None
    thesis: str = ""
    quote: dict = field(default_factory=dict)
    current_positions: list = field(default_factory=list)
    # Optional account/PnL context so drawdown/loss-streak/daily-loss caps can
    # bind on the submit path (FIX-1). Keys: account_equity, cash, buying_power,
    # daily_pnl, weekly_pnl, drawdown_pct, loss_streak. Empty => policy defaults.
    portfolio_context: dict = field(default_factory=dict)


@dataclass
class ExecutionResult:
    approved: bool
    submitted: bool
    rejected_reason: Optional[str]
    client_order_id: Optional[str]
    risk_decision: dict
    broker_response: Optional[dict]
    human_review_required: bool
    events: list
    incident: Optional[str] = None   # incident id if a post-fill safety check fired (FIX-2)


class OrderManager:
    """One instance per session. Holds the broker adapter and seen order ids."""

    def __init__(self, adapter: Optional[BrokerAdapter] = None,
                 mode: Optional[str] = None):
        # FIX-8 (P1-3): default to PAPER explicitly — never silently inherit
        # "live" from the TB_MODE env var. Callers that want another mode pass it.
        self.mode = mode if mode is not None else "paper"
        # In paper/backtest/research we never use a live adapter.
        self.adapter = adapter or NullBrokerAdapter()
        self._seen: set[str] = set()
        self._pending_symbols: set[str] = set()

    # ---- the only submit ----
    def submit(self, p: Proposal, *, human_approved: bool = False) -> ExecutionResult:
        evs: list = []
        cid = idempotency_key(p.symbol, p.side, p.strategy,
                              setup=p.setup, mode=self.mode,
                              signal_hash=p.signal_hash)
        pol_v = risk_policy.version()

        def ev(t, payload):
            e = event_store.append(t, cid, payload, mode=self.mode,
                                    policy_version=pol_v, source="order_manager")
            evs.append(e["event_type"])
            return e

        def reject(reason, rd=None):
            ev("order_rejected", {"reason": reason})
            trade_journal.log("order_rejected", cid,
                              {"symbol": p.symbol, "strategy": p.strategy, "reason": reason})
            return ExecutionResult(False, False, reason, cid,
                                   rd or {}, None, False, evs)

        ev("order_proposed", {"symbol": p.symbol, "side": p.side, "strategy": p.strategy,
                              "setup": p.setup, "entry": p.entry, "stop": p.stop_loss,
                              "evidence_source": p.evidence_source, "agent": p.source_agent})

        # 0. Backtest/research/replay never place orders.
        if self.mode in ("backtest", "research", "replay"):
            return reject(f"mode={self.mode} never submits orders")

        # 1. Config guard (mode + policy + kill switch readable).
        ok, reasons = config_guard.safe_to_trade(self.mode)
        ev("config_checked", {"ok": ok, "reasons": reasons})
        if not ok:
            return reject("config_guard: " + "; ".join(reasons))

        # 1b. GO-LIVE GATE (live only). The 7-gate authority is no longer
        # advisory: a LIVE order is refused unless every gate is green. Paper
        # is unaffected. Fail-closed — if the verdict can't be read, live stops.
        if str(self.mode) == "live":
            try:
                from lab import go_live
                reason = go_live.gate_reason_for_live()
            except Exception as e:
                reason = f"go-live verdict unavailable ({type(e).__name__}) — fail-closed"
            ev("go_live_checked", {"blocked": bool(reason), "reason": reason})
            if reason:
                return reject(f"go-live gate: {reason}")

        # 2. Kill switch / pause.
        blocked = kill_switch.blocked(symbol=p.symbol, strategy=p.strategy)
        ev("kill_switch_checked", {"blocked": blocked})
        if blocked:
            return reject(f"kill switch/pause: {blocked}")

        # 2b. Open BLOCKING incident halts new entries (red-team fix, fail-closed).
        # A blocking/incident/critical incident — e.g. a prior fill left without a
        # broker-verified stop (FIX-2) — must stop further entries until resolved.
        # Previously incidents were recorded but never consulted here.
        try:
            from safety import incident_manager
            if incident_manager.blocks_new_entries():
                openi = [i.get("incident_id") for i in incident_manager.open_incidents()
                         if i.get("severity") in ("blocking", "incident", "critical")]
                ev("incident_block_checked", {"blocked": True, "incidents": openi[:5]})
                return reject("blocking incident open — new entries halted "
                              f"({', '.join(openi[:3]) or 'unknown'})")
            ev("incident_block_checked", {"blocked": False})
        except Exception as e:
            return reject(f"incident state unreadable (fail-closed): {type(e).__name__}")

        # 3. Quote validation (fail-closed on unknown).
        qc = quote_validator.validate(p.quote or {}, intraday=True)
        ev("data_checked", {"ok": qc.ok, "reasons": qc.reasons,
                            "spread_bps": qc.spread_bps, "session": qc.market_session})
        if not qc.ok:
            return reject("quote: " + "; ".join(qc.reasons))

        # 4. Portfolio + risk gate (the sizing + exposure authority).
        rd = risk_gate.check(p.symbol, p.side, p.strategy, entry=p.entry,
                             stop_loss=p.stop_loss, take_profit=p.take_profit,
                             confidence=p.confidence,
                             current_positions=p.current_positions, mode=self.mode)
        ev("risk_checked", {"approved": rd.approved, "reason": rd.rejected_reason,
                            "shares": rd.suggested_position_size})
        if not rd.approved:
            return reject(f"risk_gate: {rd.rejected_reason}", rd.to_dict() if hasattr(rd, "to_dict") else {})

        # 4b. Portfolio engine constraints — fed REAL state so the sector,
        # correlated-cluster, heat, drawdown and loss-streak caps actually BIND
        # on the submit path (FIX-1, P0-3). Previously PortfolioState was built
        # empty (qty=1, no sector_map, no equity/PnL/drawdown), so those caps
        # could never fire.
        try:
            from portfolio.portfolio_engine import validate_trade
            from portfolio.portfolio_state import PortfolioState, Position
            from portfolio import sector_map as _sectors
            shares = rd.suggested_position_size or 0
            smap = _sectors.load()
            ctx = dict(getattr(p, "portfolio_context", None) or {})
            eq = float(ctx.get("account_equity",
                               risk_policy.get("account", "default_equity_usd", 50000)) or 50000)
            positions = [Position(symbol=str(x.get("symbol", "")).upper(),
                                  qty=float(x.get("qty", 1) or 1),
                                  entry=float(x.get("entry", x.get("last", 0)) or 0),
                                  last=float(x.get("last", x.get("entry", 0)) or 0),
                                  stop=x.get("stop"),
                                  sector=x.get("sector") or smap.get(str(x.get("symbol", "")).upper()))
                         for x in (p.current_positions or [])]
            pstate = PortfolioState(
                mode=self.mode, account_equity=eq,
                cash=float(ctx.get("cash", eq)),
                buying_power=float(ctx.get("buying_power", eq)),
                positions=positions, sector_map=smap,
                daily_pnl=float(ctx.get("daily_pnl", 0.0)),
                weekly_pnl=float(ctx.get("weekly_pnl", 0.0)),
                drawdown_pct=float(ctx.get("drawdown_pct", 0.0)),
                loss_streak=int(ctx.get("loss_streak", 0)))
            new_sector = smap.get(str(p.symbol).upper())
            pchk = validate_trade(p.symbol, p.side, shares, p.entry, p.stop_loss,
                                  pstate, sector=new_sector)
        except Exception as e:
            pchk = {"allowed": False, "violations": [f"portfolio engine error: {e}"], "exposure_after": {}}
        ev("portfolio_checked", {"allowed": pchk["allowed"], "violations": pchk["violations"],
                                 "exposure_after": pchk.get("exposure_after")})
        if not pchk["allowed"]:
            return reject("portfolio: " + "; ".join(pchk["violations"]))

        # 5. Idempotency — same signal same day cannot create two orders.
        if cid in self._seen:
            return reject(f"duplicate order (idempotency {cid})")
        # duplicate OPEN position guard (no pyramiding unless policy allows)
        allow_pyr = bool(risk_policy.get("trade_risk", "allow_pyramiding", False))
        held = {x.get("symbol", "").upper() for x in (p.current_positions or [])}
        if not allow_pyr and p.symbol.upper() in held:
            return reject("duplicate open position (pyramiding disabled)")
        if not allow_pyr and p.symbol.upper() in self._pending_symbols:
            return reject("duplicate pending order (pyramiding disabled)")

        try:
            broker_positions = self.adapter.get_positions()
            broker_open_orders = self.adapter.get_open_orders()
        except Exception as e:
            ev("broker_state_checked", {"ok": False, "error_type": type(e).__name__})
            return reject(f"broker state unavailable: {type(e).__name__} — fail-closed")
        broker_held = {str(x.get("symbol", "")).upper() for x in (broker_positions or [])}
        broker_pending = {str(x.get("symbol", "")).upper() for x in (broker_open_orders or [])}
        ev("broker_state_checked", {"ok": True, "held": sorted(broker_held),
                                    "pending": sorted(broker_pending)})
        sym = p.symbol.upper()
        if not allow_pyr and sym in broker_held:
            return reject("broker already has position (pyramiding disabled)")
        if not allow_pyr and sym in broker_pending:
            return reject("broker already has open order (pyramiding disabled)")

        # 6. Human-review gate.
        if rd.human_review_required and not human_approved:
            ev("human_review_required", {"reason": "policy threshold"})
            return reject("human review required (not approved)", rd.to_dict() if hasattr(rd, "to_dict") else {})

        # 7. Build approved intent and place via adapter (the ONLY write).
        intent = Order(symbol=p.symbol, side=p.side, strategy=p.strategy,
                       setup=p.setup, signal_hash=p.signal_hash,
                       qty=rd.suggested_position_size, order_type="limit",
                       limit_price=p.entry, entry=p.entry, stop_loss=p.stop_loss,
                       take_profit=p.take_profit, confidence=p.confidence,
                       mode=self.mode, broker=self.adapter.name,
                       evidence_source=p.evidence_source, policy_version=pol_v,
                       client_order_id=cid, approved_by_risk=True,
                       approved_by_human=human_approved, state="proposed")
        # Advance through the lifecycle state machine (illegal jumps raise).
        intent.state = order_lifecycle.transition(intent.state, "approved")
        ev("order_approved", {"shares": intent.qty, "client_order_id": cid})
        trade_journal.log("order_approved", cid,
                          {"symbol": p.symbol, "strategy": p.strategy,
                           "shares": intent.qty, "max_loss": rd.max_loss_amount})

        intent.state = order_lifecycle.transition(intent.state, "submitted")
        try:
            resp = self.adapter.submit(intent)
        except Exception as e:
            ev("order_submit_failed", {"broker": self.adapter.name,
                                       "client_order_id": cid,
                                       "error_type": type(e).__name__})
            trade_journal.log("order_rejected", cid,
                              {"symbol": p.symbol, "strategy": p.strategy,
                               "reason": f"broker submit failed: {type(e).__name__}"})
            return ExecutionResult(False, False,
                                   f"broker submit failed: {type(e).__name__}: {e}",
                                   cid,
                                   rd.to_dict() if hasattr(rd, "to_dict") else {},
                                   None, rd.human_review_required, evs)
        self._seen.add(cid)
        ev("order_submitted", {"broker": self.adapter.name, "client_order_id": cid})
        broker_ok = str(resp.get("status", "")).lower() not in ("rejected", "error")
        if broker_ok:
            self._pending_symbols.add(p.symbol.upper())
        intent.state = order_lifecycle.transition(
            intent.state, "acknowledged" if broker_ok else "rejected_by_broker")
        ev("broker_acknowledged", {"status": resp.get("status"), "state": intent.state})

        # 7b. POST-FILL protective-stop VERIFICATION (FIX-2, P0-4). Only when the
        # broker actually FILLED. A fill whose protective stop cannot be VERIFIED
        # at the broker is a blocking incident — not an inferred "attached".
        incident_id = None
        status_l = str(resp.get("status", "")).lower()
        filled = broker_ok and (status_l in ("filled", "partially_filled")
                                or float(resp.get("filled_qty") or 0) > 0)
        if filled and intent.stop_loss:
            from execution import protective_orders
            prot = protective_orders.verify_after_fill(self.adapter, intent, resp)
            if prot["verified"]:
                ev("stop_attached", {"checks": prot["checks"]})
            else:
                ev("stop_attach_failed", {"checks": prot["checks"], "reasons": prot["reasons"]})
                try:
                    from safety import incident_manager
                    inc = incident_manager.record(
                        "blocking", "execution",
                        f"filled {intent.symbol} entry without a verified protective stop",
                        symbol=intent.symbol, strategy=intent.strategy,
                        evidence={"client_order_id": cid, **prot["checks"]})
                    incident_id = inc.incident_id
                except Exception as e:
                    incident_id = f"incident-record-failed:{type(e).__name__}"
                ev("incident_raised", {"incident_id": incident_id,
                                       "severity": "blocking", "category": "execution"})
                trade_journal.log("incident_filled_without_stop", cid,
                                  {"symbol": intent.symbol, "incident": incident_id})

        ev("journal_complete", {"client_order_id": cid})

        return ExecutionResult(True, True, None, cid,
                               rd.to_dict() if hasattr(rd, "to_dict") else {},
                               resp, rd.human_review_required, evs, incident_id)


def dry_run(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
            entry=200.0, stop=190.0, target=230.0, confidence=0.7) -> ExecutionResult:
    """Show exactly what would happen, with rejection reasons. No real order."""
    os.environ.setdefault("TB_MODE", "paper")
    om = OrderManager(mode="paper")
    q = {"bid": entry - 0.02, "ask": entry + 0.02, "last": entry,
         "ts_age_seconds": 5, "avg_dollar_volume": 5e8, "tradable": True}
    return om.submit(Proposal(symbol, side, strategy, setup, entry, stop, target,
                              confidence, quote=q), human_approved=True)


if __name__ == "__main__":
    import json
    r = dry_run()
    print(json.dumps({"approved": r.approved, "submitted": r.submitted,
                      "reason": r.rejected_reason, "cid": r.client_order_id,
                      "events": r.events}, indent=2))
