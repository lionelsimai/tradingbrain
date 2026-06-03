import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import risk_policy

def test_loads_and_versions():
    assert risk_policy.version().startswith("rp_")

def test_default_mode_paper():
    assert risk_policy.get("environment","default_mode") == "paper"

def test_live_disabled_by_default():
    assert risk_policy.get("environment","live_trading_enabled") is False

def test_no_conflicts():
    assert risk_policy.report()["valid"], risk_policy.report()["conflicts"]

def test_typed_accessor_bounds():
    assert 0 < risk_policy.get("trade_risk","risk_per_trade_pct") <= 5


def test_short_selling_disabled_long_only():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from safety import risk_gate, kill_switch
    kill_switch.release()
    r = risk_gate.check("NVDA", "sell", "X", entry=212, stop_loss=220, confidence=0.7)
    assert not r.approved and "short" in r.rejected_reason.lower()

def test_invalid_side_rejected():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from safety import risk_gate, kill_switch
    kill_switch.release()
    r = risk_gate.check("NVDA", "hold", "X", entry=212, stop_loss=200, confidence=0.7)
    assert not r.approved
