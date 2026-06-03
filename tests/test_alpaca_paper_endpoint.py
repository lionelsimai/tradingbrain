import importlib

import pytest


def test_alpaca_mirror_accepts_only_paper_v2_endpoint(monkeypatch):
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")
    import scripts.broker_alpaca as broker_alpaca
    broker_alpaca = importlib.reload(broker_alpaca)

    assert broker_alpaca.validate_base_url() == "https://paper-api.alpaca.markets/v2"


def test_alpaca_mirror_rejects_live_endpoint(monkeypatch):
    monkeypatch.setenv("APCA_API_BASE_URL", "https://api.alpaca.markets/v2")
    import scripts.broker_alpaca as broker_alpaca
    broker_alpaca = importlib.reload(broker_alpaca)

    with pytest.raises(RuntimeError, match="refuses non-paper endpoint"):
        broker_alpaca.validate_base_url()


def test_alpaca_mirror_does_not_double_v2_prefix(monkeypatch):
    monkeypatch.setenv("APCA_API_BASE_URL", "https://paper-api.alpaca.markets/v2")
    import scripts.broker_alpaca as broker_alpaca
    broker_alpaca = importlib.reload(broker_alpaca)

    assert broker_alpaca.api_url("/account") == "https://paper-api.alpaca.markets/v2/account"
    assert broker_alpaca.api_url("/v2/account") == "https://paper-api.alpaca.markets/v2/account"
