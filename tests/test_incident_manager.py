import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety import incident_manager, kill_switch


def setup_function(_):
    kill_switch.release()
    incident_manager.clear_all()


def teardown_function(_):
    kill_switch.release()
    incident_manager.clear_all()


def test_blocking_incident_blocks_new_entries():
    inc = incident_manager.create_incident(
        severity="blocking", category="execution", description="quantity mismatch")
    assert inc["blocks_new_entries"] is True
    assert incident_manager.blocks_new_entries() is True


def test_critical_incident_engages_kill_switch():
    incident_manager.create_incident(
        severity="critical", category="execution", description="filled without stop")
    assert incident_manager.blocks_new_entries() is True
    assert kill_switch.is_halted() is True


def test_resolve_incident_removes_block():
    inc = incident_manager.create_incident(
        severity="blocking", category="data", description="stale quote")
    incident_manager.resolve_incident(inc["incident_id"], "operator reviewed")
    assert incident_manager.blocks_new_entries() is False
