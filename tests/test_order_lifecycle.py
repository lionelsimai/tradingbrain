import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_lifecycle as L
import pytest

def test_valid_transition():
    assert L.can("proposed","approved")
    assert L.transition("approved","submitted") == "submitted"

def test_invalid_transition_raises():
    with pytest.raises(L.InvalidTransition):
        L.transition("proposed","filled")

def test_rejected_is_terminal():
    assert L.is_terminal("rejected_pretrade")
    assert not L.can("rejected_pretrade","filled")

def test_filled_to_stop_path():
    assert L.can("filled","stop_pending")
    assert L.can("stop_pending","protective_order_failed")


def test_order_manager_wires_lifecycle(monkeypatch):
    """An approved order must advance through the state machine to 'acknowledged'."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from data import market_calendar
    from execution import order_manager as om
    from execution.paper_adapter import PaperAdapter
    from safety import kill_switch
    kill_switch.release()
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    adapter = PaperAdapter(equity=50000)
    adapter.set_quote("NVDA", bid=199.98, ask=200.02, last=200.0)
    q = {"bid": 199.98, "ask": 200.02, "last": 200.0, "ts_age_seconds": 5,
         "avg_dollar_volume": 5e8, "tradable": True, "market_session": "regular"}
    mgr = om.OrderManager(mode="paper", adapter=adapter)
    r = mgr.submit(om.Proposal("NVDA", "buy", "TREND_LEADER", "TREND_LEADER",
                   200.0, 190.0, 230.0, 0.7, quote=q), human_approved=True)
    assert r.approved and r.submitted, r.rejected_reason
    assert "broker_acknowledged" in r.events
