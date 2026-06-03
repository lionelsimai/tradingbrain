import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import live_feature_preflight


def test_live_feature_preflight_never_enables_execution(monkeypatch):
    monkeypatch.setenv("TB_MODE", "paper")
    monkeypatch.setenv("TB_ALLOW_LIVE", "0")
    monkeypatch.setenv("TB_HUMAN_APPROVED", "0")

    report = live_feature_preflight.run(require_realtime_data=False)

    assert report["verdict"] == "LIVE_EXECUTION_LOCKED"
    assert report["execution_enabled"] is False
    assert report["live_execution_authorized"] is False
    assert report["read_only_live_features_enabled"] is True
    assert "Do not enable live trading" in report["forbidden_next_action"]


def test_live_feature_preflight_blocks_live_flags(monkeypatch):
    monkeypatch.setenv("TB_MODE", "live")
    monkeypatch.setenv("TB_ALLOW_LIVE", "1")

    report = live_feature_preflight.run(require_realtime_data=False)
    blocker_ids = {b["id"] for b in report["blockers"]}

    assert report["execution_enabled"] is False
    assert report["live_execution_authorized"] is False
    assert "unsafe_live_flags_requested" in blocker_ids
