from safety import live_readiness


def test_world_class_readiness_does_not_average_away_paper_gap():
    report = live_readiness.evaluate()

    assert report["verdict"] == "LIVE_BLOCKED"
    assert report["live_trading_enabled"] is False
    assert report["paper_evidence"]["paper_resolved"] < 50
    assert any(b["id"] == "paper_evidence_thin" for b in report["blockers"])
