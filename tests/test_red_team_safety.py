#!/usr/bin/env python3
"""Red-team: try to make the system do something unsafe. Each must be impossible."""
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TB_MODE", "paper")

PROD_GLOBS = ["safety", "execution", "journal", "data", "scripts", "loops", "backtest"]


def _prod_files():
    out = []
    for d in PROD_GLOBS:
        out += [p for p in (ROOT / d).rglob("*.py") if "__pycache__" not in str(p)]
    return out


def test_active_alpaca_wrapper_is_read_only():
    w = (ROOT / "scripts" / "wrappers" / "alpaca.sh").read_text()
    # No write verbs actually executed (POST/DELETE to orders/positions).
    assert "-X POST" not in w and "-X DELETE" not in w
    assert "REFUSED" in w  # write subcommands are refused


def test_no_unsafe_curl_in_production():
    bad = []
    for p in _prod_files():
        t = p.read_text()
        if re.search(r"-X\s+(POST|DELETE).*(/v2/orders|/v2/positions)", t):
            bad.append(str(p))
    assert not bad, f"raw broker write calls found in: {bad}"


def test_only_order_manager_calls_adapter_submit():
    offenders = []
    for p in _prod_files():
        if p.name in ("order_manager.py", "broker_base.py"):
            continue
        t = p.read_text()
        if re.search(r"\.submit\(\s*intent", t) or "adapter.submit(" in t:
            offenders.append(str(p))
    assert not offenders, f"adapter.submit called outside order_manager: {offenders}"


def test_agents_do_not_import_broker_or_order_manager():
    agents = list((ROOT / "scripts" / "agents").rglob("*.py"))
    bad = []
    for p in agents:
        t = p.read_text()
        if "broker_base" in t or "alpaca" in t.lower() or "order_manager" in t:
            bad.append(str(p))
    assert not bad, f"agent imports execution/broker: {bad}"


def test_live_mode_fails_closed_without_flags(monkeypatch):
    from safety import config_guard
    monkeypatch.setenv("TB_MODE", "live")
    monkeypatch.delenv("TB_ALLOW_LIVE", raising=False)
    ok, reasons = config_guard.safe_to_trade("live")
    assert not ok and any("live" in r.lower() for r in reasons)


def test_live_adapter_cannot_be_instantiated():
    from execution.broker_base import DisabledLiveAdapter, DisabledLiveTradingError
    with pytest.raises(DisabledLiveTradingError):
        DisabledLiveAdapter()


def test_policy_conflict_is_detected():
    from safety import risk_policy
    # current repo should be conflict-free after migration
    assert risk_policy.conflicts() == [], risk_policy.conflicts()


def test_no_secrets_printed_in_logging():
    from safety.logging_setup import _mask
    masked = _mask("APCA_API_SECRET_KEY=abcdEFGH1234 and token=zzz")
    assert "abcdEFGH1234" not in masked


def test_quarantined_wrapper_is_neutered():
    q = ROOT / "deprecated" / "unsafe_wrappers" / "alpaca.sh"
    assert q.exists()
    assert "QUARANTINED" in q.read_text()
