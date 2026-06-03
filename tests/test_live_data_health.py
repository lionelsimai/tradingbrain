from monitoring import live_data_health


def test_live_data_health_fails_closed_when_moomoo_opend_offline(monkeypatch):
    monkeypatch.setenv("TB_MODE", "paper")
    monkeypatch.setenv("TB_ALLOW_LIVE", "0")

    report = live_data_health.check(
        require_realtime=True,
        host="127.0.0.1",
        port=9,
    )

    assert report["ok"] is False
    assert report["providers"]["moomoo"]["market_data_only"] is True
    assert any("moomoo OpenD is not reachable" in f for f in report["hard_failures"])


def test_live_data_health_refuses_live_execution_flags(monkeypatch):
    monkeypatch.setenv("TB_MODE", "live")
    monkeypatch.setenv("TB_ALLOW_LIVE", "1")

    report = live_data_health.check(require_realtime=False)

    assert report["ok"] is False
    assert report["safety"]["live_trading_enabled"] is False
    assert any("live execution flags" in f for f in report["hard_failures"])
