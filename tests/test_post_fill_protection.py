"""FIX-2 (P0-4): a fill whose protective stop cannot be VERIFIED at the broker
must raise a blocking incident — not be inferred 'attached' from a status string.
A normal paper fill (stop carried on the position) must verify clean.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om
from execution.broker_base import NullBrokerAdapter
from safety import kill_switch, incident_manager
from data import market_calendar


def _prop(**k):
    entry = k.get("entry", 212.65)
    base = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
                entry=entry, stop_loss=206.0, take_profit=236.0, confidence=0.7,
                quote=dict(bid=entry - 0.05, ask=entry + 0.05, last=entry, ts_age_seconds=2,
                           avg_dollar_volume=5e8, tradable=True),
                current_positions=[])
    base.update(k)
    return om.Proposal(**base)


class _FilledNoStop(NullBrokerAdapter):
    """Broker that FILLS the entry but attaches NO protective stop."""
    name = "paper"

    def __init__(self):
        super().__init__()
        self._filled = False
        self._sym = None

    def _place(self, intent):
        self._filled = True
        self._sym = intent.symbol
        return {"broker": "paper", "client_order_id": intent.client_order_id,
                "status": "filled", "filled_qty": intent.qty}

    def get_positions(self):
        if not self._filled:
            return []
        return [{"symbol": self._sym, "qty": 1, "entry": 0.0, "last": 0.0, "stop": None}]

    def get_open_orders(self):
        return []


class _FilledWithStop(_FilledNoStop):
    """Broker that FILLS the entry WITH the protective stop on the position."""

    def get_positions(self):
        if not self._filled:
            return []
        return [{"symbol": self._sym, "qty": 1, "entry": 0.0, "last": 0.0, "stop": 206.0}]


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_INCIDENTS_DIR", str(tmp_path / "incidents"))
    incident_manager._default = None     # force re-read against the tmp dir
    incident_manager.clear_all()
    kill_switch.release()


def teardown_function(_):
    incident_manager._default = None
    kill_switch.release()


def test_fill_without_verified_stop_raises_blocking_incident(monkeypatch, tmp_path):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = om.OrderManager(mode="paper", adapter=_FilledNoStop()).submit(_prop(), human_approved=True)
    assert r.submitted, "the entry did reach the broker"
    assert r.incident and r.incident.startswith("INC-"), r.incident
    assert "stop_attach_failed" in r.events
    assert "incident_raised" in r.events
    assert incident_manager.blocks_new_entries() is True


def test_fill_with_verified_stop_no_incident(monkeypatch, tmp_path):
    _isolate(tmp_path, monkeypatch)
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = om.OrderManager(mode="paper", adapter=_FilledWithStop()).submit(_prop(), human_approved=True)
    assert r.submitted and r.incident is None, r.incident
    assert "stop_attached" in r.events
    assert incident_manager.blocks_new_entries() is False
