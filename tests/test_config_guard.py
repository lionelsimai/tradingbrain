import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import config_guard, kill_switch

def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()

def test_default_mode_paper(monkeypatch):
    monkeypatch.delenv("TB_MODE", raising=False)
    assert config_guard.mode() == "paper"

def test_paper_safe_with_valid_config():
    ok, reasons = config_guard.safe_to_trade("paper")
    assert ok, reasons

def test_backtest_never_trades():
    ok, _ = config_guard.safe_to_trade("backtest")
    assert not ok

def test_live_fails_closed(monkeypatch):
    monkeypatch.setenv("TB_MODE","live")
    monkeypatch.delenv("TB_ALLOW_LIVE", raising=False)
    ok, reasons = config_guard.safe_to_trade("live")
    assert not ok

def test_kill_switch_blocks_paper():
    kill_switch.engage("test")
    ok, reasons = config_guard.safe_to_trade("paper")
    assert not ok
    kill_switch.release()
