import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from execution.fake_broker_chaos import FakeBrokerChaosAdapter, run_scenario
from data import market_calendar
from safety import incident_manager, kill_switch
from safety.order import OrderIntent


def setup_function(_):
    kill_switch.release()
    incident_manager.clear_all()


def teardown_function(_):
    kill_switch.release()
    incident_manager.clear_all()


def _intent():
    return OrderIntent(symbol="NVDA", side="buy", strategy="CHAOS", qty=10,
                       order_type="limit", limit_price=100.0, stop_loss=95.0,
                       take_profit=110.0, approved_by_risk=True)


def test_reject_order_is_explicit_not_silent():
    a = FakeBrokerChaosAdapter("reject_order")
    r = a.submit(_intent())
    assert r["status"] == "rejected"
    assert r["reason"] == "reject_order"


def test_partial_fill_is_reported():
    a = FakeBrokerChaosAdapter("partial_fill")
    r = a.submit(_intent())
    assert r["status"] == "partially_filled"
    assert 0 < r["filled_qty"] < 10


def test_stop_attach_failure_creates_blocking_incident(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = run_scenario("stop_attach_failed")
    assert r.blocks_new_entries is True
    assert r.incident_id
    assert kill_switch.is_halted()
