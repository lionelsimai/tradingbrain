import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ops import incident
from safety import kill_switch

def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()

def test_critical_incident_blocks_entries():
    incident.raise_incident("reconciliation_failed","ghost position")
    assert incident.blocks_new_entries()
    kill_switch.release()

def test_each_incident_type_recordable():
    for t in incident.INCIDENT_TYPES:
        r=incident.raise_incident(t,"test",auto_halt=False)
        assert r["type"]==t and r["severity"] in incident.SEVERITY
    kill_switch.release()
