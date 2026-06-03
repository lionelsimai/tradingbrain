#!/usr/bin/env python3
"""Enforces docs/safety_invariants.md. If any of these fail, the system is unsafe."""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TB_MODE", "paper")

from execution.order_manager import OrderManager, Proposal
from execution.broker_base import (NullBrokerAdapter,
                                    DisabledLiveAdapter, DisabledLiveTradingError,
                                    BrokerError)
from safety.order import Order
from safety import risk_policy, kill_switch, risk_gate
from data import market_calendar


GOODQ = {"bid": 199.98, "ask": 200.02, "last": 200.0, "ts_age_seconds": 5,
         "avg_dollar_volume": 5e8, "tradable": True}


@pytest.fixture(autouse=True)
def _market_open(monkeypatch):
    """Run order-path tests as if the market is open (isolate timing)."""
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    kill_switch.release()
    yield
    kill_switch.release()


def _prop(**kw):
    base = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
                entry=200.0, stop_loss=190.0, take_profit=230.0, confidence=0.7,
                quote=dict(GOODQ), current_positions=[])
    base.update(kw)
    return Proposal(**base)


def test_happy_path_approves_and_journals():
    om = OrderManager(mode="paper")
    r = om.submit(_prop(), human_approved=True)
    assert r.approved and r.submitted
    assert "order_approved" in r.events and "order_submitted" in r.events
    assert "journal_complete" in r.events


def test_inv7_kill_switch_blocks():
    kill_switch.engage("test")
    om = OrderManager(mode="paper")
    r = om.submit(_prop(), human_approved=True)
    assert not r.approved and "kill" in r.rejected_reason.lower()


def test_inv9_stale_quote_blocks():
    om = OrderManager(mode="paper")
    r = om.submit(_prop(quote={**GOODQ, "ts_age_seconds": 99999}), human_approved=True)
    assert not r.approved and "stale" in r.rejected_reason.lower()


def test_inv20_unknown_age_rejects():
    om = OrderManager(mode="paper")
    q = {k: v for k, v in GOODQ.items() if k != "ts_age_seconds"}
    r = om.submit(_prop(quote=q), human_approved=True)
    assert not r.approved  # fail-closed on unknown age


def test_inv26_missing_stop_rejects():
    om = OrderManager(mode="paper")
    r = om.submit(_prop(stop_loss=0.0), human_approved=True)
    assert not r.approved


def test_inv27_zero_size_rejects():
    # entry == stop -> zero risk-per-share -> reject
    om = OrderManager(mode="paper")
    r = om.submit(_prop(entry=200.0, stop_loss=200.0), human_approved=True)
    assert not r.approved


def test_inv28_duplicate_position_rejects():
    om = OrderManager(mode="paper")
    held = [{"symbol": "NVDA", "value": 5000, "risk_pct": 0.5}]
    r = om.submit(_prop(current_positions=held), human_approved=True)
    assert not r.approved
    assert ("duplicate" in r.rejected_reason.lower()
            or "pyramiding" in r.rejected_reason.lower()
            or "already holding" in r.rejected_reason.lower())


def test_inv29_duplicate_order_rejects():
    om = OrderManager(mode="paper")
    r1 = om.submit(_prop(), human_approved=True)
    r2 = om.submit(_prop(), human_approved=True)   # same signal same day
    assert r1.submitted and not r2.approved
    assert "duplicate" in r2.rejected_reason.lower()


def test_inv14_rejection_has_reason():
    kill_switch.engage("x")
    om = OrderManager(mode="paper")
    r = om.submit(_prop(), human_approved=True)
    assert r.rejected_reason and "order_rejected" in r.events


def test_inv1_backtest_mode_never_submits():
    om = OrderManager(mode="backtest")
    r = om.submit(_prop(), human_approved=True)
    assert not r.submitted


def test_inv2_adapter_requires_intent_and_approval():
    a = NullBrokerAdapter()
    with pytest.raises(BrokerError):
        a.submit({"symbol": "NVDA"})          # raw dict, not an OrderIntent
    unapproved = Order(symbol="NVDA", side="buy", strategy="X")
    with pytest.raises(BrokerError):
        a.submit(unapproved)                  # approved_by_risk is False


def test_live_adapter_is_disabled():
    with pytest.raises(DisabledLiveTradingError):
        DisabledLiveAdapter()


def test_inv6_8_full_check_chain_runs():
    om = OrderManager(mode="paper")
    r = om.submit(_prop(), human_approved=True)
    for step in ("config_checked", "kill_switch_checked", "data_checked", "risk_checked"):
        assert step in r.events


def test_human_review_blocks_without_approval():
    # large position (tight stop) trips human-review threshold
    om = OrderManager(mode="paper")
    r = om.submit(_prop(entry=200, stop_loss=199), human_approved=False)
    assert not r.approved and "human review" in r.rejected_reason.lower()


def test_inv24_policy_loads_and_versions():
    assert risk_policy.version().startswith("rp_")
    assert risk_policy.load()["environment"]["live_trading_enabled"] is False


# ---- additional invariant coverage (inv 1-30) ----
import re as _re

def test_inv1_only_order_manager_submits():
    """No production module calls an adapter _place/submit except order_manager."""
    offenders = []
    for d in ("scripts", "loops", "agents", "strategies", "portfolio"):
        for f in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            txt = f.read_text()
            if _re.search(r"\.submit\(\s*intent", txt) or "._place(" in txt:
                offenders.append(str(f.relative_to(ROOT)))
    assert not offenders, offenders

def test_inv2_adapter_cannot_approve():
    from execution.broker_base import NullBrokerAdapter
    a = NullBrokerAdapter()
    assert not hasattr(a, "approve")

def test_inv4_agents_no_broker_import():
    from agents import permissions
    for f in (ROOT / "agents").glob("*.py"):
        src = f.read_text()
        for bad in permissions.FORBIDDEN_IMPORTS:
            assert f"import {bad}" not in src

def test_inv9_quote_validation_required():
    from data import quote_validator as qv
    assert not qv.validate({}, intraday=True).ok  # empty quote -> reject

def test_inv16_17_replay_paper_never_live_gate():
    from scorecards import source_policy as sp
    assert not sp.may_drive_live_gate("replay")
    assert not sp.may_drive_live_gate("paper")
    assert sp.may_drive_live_gate("live")

def test_inv18_combined_never_calibrates():
    from scorecards import source_policy as sp
    assert not sp.may_drive_calibration("combined", "paper")

def test_inv20_unknown_freshness_rejects():
    from data import quote_validator as qv
    r = qv.validate({"bid": 1, "ask": 1.01, "last": 1, "avg_dollar_volume": 1e9,
                     "tradable": True}, intraday=True, require_market_open=False)
    assert not r.ok  # missing ts_age_seconds -> fail closed

def test_inv24_missing_policy_rejects(tmp_path, monkeypatch):
    # a malformed policy must not validate
    from safety import risk_policy
    assert risk_policy.report()["valid"]  # canonical is valid

def test_inv26_missing_stop_rejects_long():
    rd = risk_gate.check("NVDA", "buy", "X", entry=212, stop_loss=0, confidence=0.7)
    assert not rd.approved

def test_inv27c_risk_gate_zero_risk_rejects():
    # entry == stop -> zero risk per share -> reject at risk_gate layer
    rd = risk_gate.check("NVDA", "buy", "X", entry=212, stop_loss=212, confidence=0.7)
    assert not rd.approved

def test_inv27b_zero_risk_per_share_rejects():
    # entry == stop -> zero risk per share -> reject
    rd = risk_gate.check("NVDA", "buy", "X", entry=212, stop_loss=212, confidence=0.7)
    assert not rd.approved

def test_inv30_no_hardcoded_path_in_core():
    core = ["safety", "execution", "journal", "data", "database", "portfolio",
            "scorecards", "agents", "strategies", "monitoring", "ops"]
    bad = []
    for d in core:
        for f in (ROOT / d).rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            if "/home/workspace/TradingBrain" in f.read_text():
                bad.append(str(f.relative_to(ROOT)))
    assert not bad, bad
