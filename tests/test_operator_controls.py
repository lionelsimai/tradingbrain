import subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from safety import kill_switch, risk_gate

def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()

def _op(*a):
    return subprocess.run([sys.executable,"-m","safety.operator",*a],
        cwd=ROOT, capture_output=True, text=True)

def test_status_runs():
    assert _op("status").returncode==0

def test_kill_blocks_then_release():
    kill_switch.engage("drill")
    d=risk_gate.check("NVDA","buy","X",entry=212,stop_loss=206,confidence=0.7)
    assert not d.approved
    kill_switch.release()
    assert kill_switch.blocked() is None

def test_pause_symbol_blocks():
    kill_switch.pause_symbol("NVDA")
    assert kill_switch.blocked(symbol="NVDA")
    kill_switch.resume_symbol("NVDA")

def test_pause_strategy_blocks():
    kill_switch.pause_strategy("VCP")
    assert kill_switch.blocked(strategy="VCP")
    kill_switch.resume_strategy("VCP")

def test_health_command():
    assert _op("health").returncode==0
