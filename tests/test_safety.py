#!/usr/bin/env python3
"""Critical safety tests — the audit's must-pass list. Every one of these
encodes a way the system could lose uncontrolled money; each must stay green.

Run: python3 -m pytest tests/test_safety.py -q
"""
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT))

from safety import config_guard, kill_switch, risk_gate, trade_journal  # noqa: E402
from safety.order import Order, idempotency_key  # noqa: E402
from safety.logging_setup import _mask  # noqa: E402

CB = ROOT / "reports" / "circuit-breakers.json"
STATE = ROOT / "reports" / "safety_state.json"

OK = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER",
          entry=200.0, stop_loss=190.0, take_profit=230.0, confidence=0.7,
          current_positions=[], data_age_minutes=30, mode="paper")


@pytest.fixture(autouse=True)
def isolate_state():
    """Back up and restore safety state + circuit breaker files around each test."""
    cb_bak = CB.read_text() if CB.exists() else None
    st_bak = STATE.read_text() if STATE.exists() else None
    kill_switch.release()
    if CB.exists():
        CB.unlink()
    yield
    CB.write_text(cb_bak) if cb_bak is not None else (CB.exists() and CB.unlink())
    STATE.write_text(st_bak) if st_bak is not None else (STATE.exists() and STATE.unlink())
    kill_switch.release()


def _cb(scalar, reason="test"):
    CB.write_text(json.dumps({"sizing_scalar": scalar, "reason": reason}))


# --- the baseline must approve, else other tests are meaningless ---
def test_clean_trade_approved():
    assert risk_gate.check(**OK).approved


# --- CRITICAL: kill switch blocks orders ---
def test_kill_switch_blocks_orders():
    kill_switch.engage("unit test")
    d = risk_gate.check(**OK)
    assert not d.approved
    assert "kill switch" in d.rejected_reason.lower()


def test_symbol_pause_blocks_orders():
    kill_switch.pause_symbol("NVDA")
    assert not risk_gate.check(**OK).approved
    kill_switch.resume_symbol("NVDA")
    assert risk_gate.check(**OK).approved


# --- CRITICAL: circuit breaker / daily loss / drawdown halt blocks orders ---
def test_circuit_breaker_halt_blocks_orders():
    _cb(0.0, "daily loss -4% -> HALT")
    d = risk_gate.check(**OK)
    assert not d.approved
    assert "circuit breaker" in d.rejected_reason.lower()


def test_circuit_breaker_scalar_reduces_size():
    _cb(0.5, "daily loss -2% -> halve")
    half = risk_gate.check(**OK).suggested_position_size
    CB.unlink()
    full = risk_gate.check(**OK).suggested_position_size
    assert 0 < half < full


# --- CRITICAL: stale data blocks orders ---
def test_stale_data_blocks_orders():
    bad = {**OK, "data_age_minutes": 60 * 48}
    assert not risk_gate.check(**bad).approved


# --- price/stop sanity ---
def test_bad_stop_blocks_orders():
    assert not risk_gate.check(**{**OK, "stop_loss": 210.0}).approved  # stop above entry on a long
    assert not risk_gate.check(**{**OK, "entry": 0}).approved


# --- confidence floor ---
def test_low_confidence_blocked():
    assert not risk_gate.check(**{**OK, "confidence": 0.1}).approved


# --- portfolio: no pyramiding, max concurrent ---
def test_no_pyramiding():
    pos = [{"symbol": "NVDA", "value": 5000, "risk_pct": 1.0}]
    assert not risk_gate.check(**{**OK, "current_positions": pos}).approved


def test_max_concurrent_blocks():
    pos = [{"symbol": f"T{i}", "value": 1000, "risk_pct": 0.5} for i in range(6)]
    assert not risk_gate.check(**{**OK, "current_positions": pos}).approved


# --- position sizing: capped, never zero-through ---
def test_position_size_capped_and_positive():
    d = risk_gate.check(**OK)
    assert d.suggested_position_size > 0
    assert d.suggested_position_size <= d.max_position_size
    assert d.max_loss_amount > 0


# --- CRITICAL: duplicate signal -> same idempotency key -> no duplicate order ---
def test_idempotency_prevents_duplicate_orders():
    k1 = idempotency_key("NVDA", "buy", "TREND_LEADER", "2026-05-30")
    k2 = idempotency_key("nvda", "BUY", "TREND_LEADER", "2026-05-30")
    assert k1 == k2
    assert Order(symbol="NVDA", side="buy", strategy="X").client_order_id == \
           Order(symbol="NVDA", side="buy", strategy="X").client_order_id


def test_idempotency_includes_setup_mode_and_signal_hash_when_present():
    k1 = idempotency_key("NVDA", "buy", "TREND_LEADER", "2026-05-30",
                         setup="Breakout", mode="Paper", signal_hash="ABC123")
    k2 = idempotency_key("nvda", "BUY", "trend_leader", "2026-05-30",
                         setup="breakout", mode="paper", signal_hash="abc123")
    k3 = idempotency_key("NVDA", "buy", "TREND_LEADER", "2026-05-30",
                         setup="MeanReversion", mode="paper", signal_hash="abc123")
    assert k1 == k2
    assert k1 != k3


# --- CRITICAL: paper/live separation, live fails closed ---
def test_live_fails_closed_without_flag(monkeypatch):
    monkeypatch.delenv("TB_ALLOW_LIVE", raising=False)
    ok, reasons = config_guard.safe_to_trade("live")
    assert not ok
    assert any("TB_ALLOW_LIVE" in r for r in reasons)


def test_default_mode_is_paper(monkeypatch):
    monkeypatch.delenv("TB_MODE", raising=False)
    assert config_guard.mode() == "paper"


def test_backtest_mode_never_trades():
    ok, reasons = config_guard.safe_to_trade("backtest")
    assert not ok


# --- CRITICAL: secrets never logged ---
def test_secrets_are_masked():
    masked = _mask("APCA_API_KEY_ID=ABCD1234SECRETXYZ token=sk-abcdef123456")
    assert "ABCD1234SECRETXYZ" not in masked
    assert "sk-abcdef123456" not in masked


def test_config_mask_helper():
    assert config_guard.mask("ABCD1234SECRET").startswith("AB")
    assert "1234" not in config_guard.mask("ABCD1234SECRET")


# --- config validation catches dangerous values ---
def test_config_validation_passes_current():
    assert config_guard.validate_config() == []


# --- audit trail round-trips ---
def test_trade_journal_reconstructs():
    coid = "tb_test_" + os.urandom(3).hex()
    trade_journal.log_idea(coid, {"symbol": "TEST"})
    trade_journal.log_risk(coid, {"approved": True})
    trade_journal.log_order(coid, {"qty": 10})
    events = trade_journal.reconstruct(coid)
    assert [e["event"] for e in events] == ["idea", "risk_decision", "order"]
