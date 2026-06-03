from scripts import red_team_live_readiness


def test_red_team_live_readiness_writes_required_schema():
    out = red_team_live_readiness.run()

    assert out["finding_count"] == 20
    assert out["verdict"] == "LIVE_BLOCKED"
    first = out["findings"][0]
    for key in (
        "id",
        "severity",
        "title",
        "evidence",
        "attack_path",
        "expected_damage",
        "fix",
        "test",
        "blocks_live",
    ):
        assert key in first
    assert any(f["id"] == "RT-LIVE-002" and f["blocks_live"] for f in out["findings"])
