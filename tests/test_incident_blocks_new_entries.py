"""Red-team P0 (Section 6#6 / 12#20): an open BLOCKING incident must halt new
entries through order_manager. Closes the confirmed gap where FIX-2 raised a
blocking incident but a subsequent entry still submitted.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om
from safety import kill_switch, incident_manager
from data import market_calendar


def _prop(**k):
    base = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
                entry=212.65, stop_loss=206.0, take_profit=236.0, confidence=0.7,
                quote=dict(bid=212.6, ask=212.7, last=212.65, ts_age_seconds=2,
                           avg_dollar_volume=5e8, tradable=True))
    base.update(k)
    return om.Proposal(**base)


def _iso(tmp_path, monkeypatch):
    monkeypatch.setenv("TB_INCIDENTS_DIR", str(tmp_path / "inc"))
    incident_manager._default = None
    incident_manager.clear_all()
    kill_switch.release()
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")


def teardown_function(_):
    incident_manager._default = None
    kill_switch.release()


def test_blocking_incident_halts_new_entries(monkeypatch, tmp_path):
    _iso(tmp_path, monkeypatch)
    # clean state approves
    assert om.OrderManager(mode="paper").submit(_prop(), human_approved=True).approved
    # an open blocking incident must reject the next entry
    incident_manager.record("blocking", "execution", "red-team: simulated open incident")
    r = om.OrderManager(mode="paper").submit(_prop(), human_approved=True)
    assert not r.approved
    assert "incident" in (r.rejected_reason or "").lower(), r.rejected_reason
    assert "kill_switch_checked" in r.events       # got past kill switch
    assert "risk_checked" not in r.events          # blocked BEFORE risk/sizing


def test_critical_incident_halts_new_entries(monkeypatch, tmp_path):
    _iso(tmp_path, monkeypatch)
    incident_manager.record("critical", "reconciliation", "red-team: ghost position",
                            engage_kill_switch=False)
    r = om.OrderManager(mode="paper").submit(_prop(), human_approved=True)
    assert not r.approved
    assert "incident" in (r.rejected_reason or "").lower()


def test_warning_incident_does_not_block(monkeypatch, tmp_path):
    _iso(tmp_path, monkeypatch)
    incident_manager.record("warning", "data", "red-team: soft warning only")
    assert om.OrderManager(mode="paper").submit(_prop(), human_approved=True).approved


def test_resolved_incident_unblocks(monkeypatch, tmp_path):
    _iso(tmp_path, monkeypatch)
    inc = incident_manager.record("blocking", "execution", "temp")
    assert not om.OrderManager(mode="paper").submit(_prop(), human_approved=True).approved
    incident_manager.resolve_incident(inc.incident_id, "operator: resolved in test")
    assert om.OrderManager(mode="paper").submit(_prop(), human_approved=True).approved
