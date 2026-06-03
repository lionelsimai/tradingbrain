import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om
from execution.broker_base import BrokerError, NullBrokerAdapter
from safety import kill_switch
from data import market_calendar

def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()

def _prop(**k):
    base=dict(symbol="NVDA",side="buy",strategy="TREND_LEADER",setup="TREND_LEADER",
        entry=212.65,stop_loss=206.0,take_profit=236.0,confidence=0.7,
        quote=dict(bid=212.5,ask=212.8,last=212.65,ts_age_seconds=2,
                   avg_dollar_volume=5e8,tradable=True),
        current_positions=[])
    base.update(k); return om.Proposal(**base)

def test_missing_stop_rejected(monkeypatch):
    monkeypatch.setattr(market_calendar,"session",lambda *a,**k:"regular")
    r=om.OrderManager(mode="paper").submit(_prop(stop_loss=None))
    assert not r.approved

def test_kill_switch_rejected():
    kill_switch.engage("t")
    r=om.OrderManager(mode="paper").submit(_prop())
    assert not r.approved and "kill" in (r.rejected_reason or "").lower()
    kill_switch.release()

def test_market_closed_rejected(monkeypatch):
    monkeypatch.setattr(market_calendar,"session",lambda *a,**k:"closed")
    r=om.OrderManager(mode="paper").submit(_prop())
    assert not r.approved

def test_happy_path_approves(monkeypatch):
    monkeypatch.setattr(market_calendar,"session",lambda *a,**k:"regular")
    r=om.OrderManager(mode="paper").submit(_prop(), human_approved=True)
    assert r.approved, r.rejected_reason
    assert "order_proposed" in r.events and "order_approved" in r.events


class _AdapterWithOpenOrder(NullBrokerAdapter):
    def get_open_orders(self):
        return [{"symbol": "NVDA", "status": "accepted", "client_order_id": "tb_existing"}]


class _AdapterWithSubmitFailure(NullBrokerAdapter):
    def _place(self, intent):
        raise BrokerError("simulated broker outage")


def test_broker_open_order_blocks_duplicate_symbol(monkeypatch):
    monkeypatch.setattr(market_calendar,"session",lambda *a,**k:"regular")
    r=om.OrderManager(mode="paper", adapter=_AdapterWithOpenOrder()).submit(
        _prop(setup="BREAKOUT"), human_approved=True)
    assert not r.approved
    assert "open order" in (r.rejected_reason or "").lower()
    assert "broker_state_checked" in r.events
    assert "order_submitted" not in r.events


def test_broker_submit_failure_returns_rejection_event(monkeypatch):
    monkeypatch.setattr(market_calendar,"session",lambda *a,**k:"regular")
    r=om.OrderManager(mode="paper", adapter=_AdapterWithSubmitFailure()).submit(
        _prop(), human_approved=True)
    assert not r.approved and not r.submitted
    assert "broker submit failed" in (r.rejected_reason or "").lower()
    assert "order_submit_failed" in r.events
