import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents import permissions
from agents.schemas import ReportingAgent
import pytest

def test_no_agent_can_submit():
    for a in permissions.AGENT_PERMISSIONS:
        assert not permissions.can(a,"submit_order")
        assert not permissions.can(a,"call_broker")

def test_agent_blocked_at_runtime():
    with pytest.raises(PermissionError):
        ReportingAgent().submit_order()

def test_agent_source_no_broker_import():
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    for f in agents_dir.glob("*.py"):
        src = f.read_text()
        for bad in permissions.FORBIDDEN_IMPORTS:
            assert f"import {bad}" not in src, f"{f.name} imports {bad}"

def test_invalid_output_rejected():
    ok,_=permissions.validate_output("signal_agent",{"type":"x","qty":5})
    assert not ok
