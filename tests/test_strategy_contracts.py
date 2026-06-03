import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from strategies.base import SignalCandidate, Strategy

def _sig(**k):
    base=dict(signal_id="s",timestamp="t",symbol="NVDA",direction="long",
        strategy="X",setup="X",confidence=0.7,entry_condition="e",
        invalidation_condition="i",stop_loss=200.0,take_profit=230.0,
        expected_holding_period=10)
    base.update(k); return SignalCandidate(**base)

def test_valid_signal():
    assert _sig().symbol=="NVDA"

def test_no_stop_rejected():
    with pytest.raises(ValueError):
        _sig(stop_loss=0)

def test_bad_direction_rejected():
    with pytest.raises(ValueError):
        _sig(direction="sideways")

def test_strategy_cannot_submit():
    class S(Strategy):
        def generate(self, m): return []
    with pytest.raises(PermissionError):
        S().submit()
