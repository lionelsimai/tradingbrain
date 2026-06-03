"""FIX-4 (P0-2): a FAILING portfolio PBO (setup selection overfit, worse than
random) must GATE every setup off in the live path — not be computed by the
gauntlet and then ignored by calibration (the original finding: PBO 92.9% yet all
setups enabled:true)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import calibration


def test_failing_pbo_disables_all_setups(monkeypatch):
    monkeypatch.setattr(calibration, "portfolio_pbo_pass", lambda: False)   # e.g. 92.9%
    monkeypatch.setattr(calibration, "load",
                        lambda: {"BREAKOUT": {"enabled": True}, "TREND_LEADER": {"enabled": True}})
    assert calibration.is_enabled("BREAKOUT") is False
    assert calibration.is_enabled("TREND_LEADER") is False


def test_passing_pbo_respects_per_setup_enabled(monkeypatch):
    monkeypatch.setattr(calibration, "portfolio_pbo_pass", lambda: True)
    monkeypatch.setattr(calibration, "load",
                        lambda: {"BREAKOUT": {"enabled": True}, "VCP": {"enabled": False}})
    assert calibration.is_enabled("BREAKOUT") is True
    assert calibration.is_enabled("VCP") is False


def test_absent_pbo_is_graceful(monkeypatch):
    monkeypatch.setattr(calibration, "portfolio_pbo_pass", lambda: None)
    monkeypatch.setattr(calibration, "load", lambda: {"BREAKOUT": {"enabled": True}})
    assert calibration.is_enabled("BREAKOUT") is True


def test_reader_finds_pbo_in_real_nested_shape(tmp_path, monkeypatch):
    """Catches the nesting bug: pbo lives under 'checks', not at the root. This
    tests the READER against the real shape, not a mock of it."""
    import json as _json
    g = tmp_path / "gauntlet.json"
    g.write_text(_json.dumps({"verdict": "REJECTED", "checks": {
        "deflated_sharpe": {"value": 0.97, "pass": True},
        "pbo": {"value_pct": 92.9, "pass": False, "n_setups": 5, "combinations": 70}}}))
    monkeypatch.setattr(calibration, "GAUNTLET", g)
    assert calibration.portfolio_pbo_pass() is False
