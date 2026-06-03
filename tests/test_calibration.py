import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import scripts.calibration as calib

def test_replay_suppress_only_not_promote():
    # replay can only suppress; live_gated needs live evidence (none -> False)
    assert calib.live_gated("VCP") is False

def test_unknown_setup_no_crash():
    assert calib.replay_negative_gated("NONEXISTENT") in (True, False)

def test_load_scorecard_sources():
    assert isinstance(calib.load_scorecard("live"), dict)
    assert isinstance(calib.load_scorecard("replay"), dict)
