from __future__ import annotations

import pytest

from execution.alpaca_paper_adapter import AlpacaPaperAdapter, DEFAULT_BASE, DEFAULT_DATA_BASE
from execution.broker_base import BrokerError
from safety.order import OrderIntent


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = "payload"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if url.endswith("/orders") and method == "GET":
            return FakeResponse([])
        if url.endswith("/orders") and method == "POST":
            payload = kwargs["json"]
            return FakeResponse(
                {
                    "id": "ord_1",
                    "client_order_id": payload["client_order_id"],
                    "symbol": payload["symbol"],
                    "status": "accepted",
                    "order_class": payload["order_class"],
                }
            )
        if "/assets/" in url:
            return FakeResponse({"symbol": url.rsplit("/", 1)[-1], "tradable": True, "status": "active"})
        if "/quotes/latest" in url:
            return FakeResponse({"quote": {"bp": 99.9, "ap": 100.1, "t": "2026-06-02T16:00:00Z"}})
        if url.endswith("/clock"):
            return FakeResponse({"is_open": True})
        if url.endswith("/account"):
            return FakeResponse({"status": "ACTIVE", "equity": "100000"})
        if url.endswith("/positions"):
            return FakeResponse([])
        return FakeResponse({})


def _adapter():
    return AlpacaPaperAdapter(
        key_id="paper_key",
        secret_key="paper_secret",
        base_url=DEFAULT_BASE,
        session=FakeSession(),
    )


def test_rejects_non_paper_endpoint():
    with pytest.raises(BrokerError, match="refuses non-paper endpoint"):
        AlpacaPaperAdapter(
            key_id="paper_key",
            secret_key="paper_secret",
            base_url="https://api.alpaca.markets/v2",
            session=FakeSession(),
        )


def test_rejects_untrusted_data_endpoint_to_protect_api_headers():
    with pytest.raises(BrokerError, match="refuses untrusted data endpoint"):
        AlpacaPaperAdapter(
            key_id="paper_key",
            secret_key="paper_secret",
            base_url=DEFAULT_BASE,
            data_url="https://example.test/v2",
            session=FakeSession(),
        )


def test_accepts_default_alpaca_data_endpoint():
    adapter = AlpacaPaperAdapter(
        key_id="paper_key",
        secret_key="paper_secret",
        base_url=DEFAULT_BASE,
        data_url=DEFAULT_DATA_BASE,
        session=FakeSession(),
    )

    assert adapter.data_url == DEFAULT_DATA_BASE


def test_rejects_unapproved_intent_via_base_contract():
    adapter = _adapter()
    intent = OrderIntent(symbol="AAOI", side="buy", strategy="X", qty=1)

    with pytest.raises(BrokerError, match="approved_by_risk"):
        adapter.submit(intent)


def test_places_only_limit_bracket_order_for_approved_paper_intent():
    adapter = _adapter()
    intent = OrderIntent(
        symbol="AAOI",
        side="buy",
        strategy="QUICK_3STOCK_MOMO",
        qty=3,
        order_type="limit",
        limit_price=100.0,
        entry=100.0,
        stop_loss=97.0,
        take_profit=106.0,
        approved_by_risk=True,
        mode="paper",
        client_order_id="tb_test",
    )

    out = adapter.submit(intent)

    assert out["status"] == "accepted"
    post = [c for c in adapter.session.calls if c["method"] == "POST"][0]
    assert post["url"] == f"{DEFAULT_BASE}/orders"
    assert post["json"]["type"] == "limit"
    assert post["json"]["order_class"] == "bracket"
    assert post["json"]["take_profit"] == {"limit_price": "106.0"}
    assert post["json"]["stop_loss"] == {"stop_price": "97.0"}


def test_normalizes_latest_quote():
    adapter = _adapter()

    quote = adapter.get_latest_quote("aaoi")

    assert quote["symbol"] == "AAOI"
    assert quote["bid"] == 99.9
    assert quote["ask"] == 100.1
    assert quote["tradable"] is True
