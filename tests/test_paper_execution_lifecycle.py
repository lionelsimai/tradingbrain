from execution.order_manager import OrderManager, Proposal
from execution.paper_adapter import PaperAdapter, PaperConfig
from data import market_calendar


def test_paper_execution_lifecycle_fill_then_stop(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    adapter = PaperAdapter(cfg=PaperConfig(partial_fill_prob=0.0, seed=7))
    adapter.set_quote("NVDA", bid=99.9, ask=100.1, last=100.0, age_s=1)
    manager = OrderManager(adapter=adapter, mode="paper")

    result = manager.submit(
        Proposal(
            symbol="NVDA",
            side="buy",
            strategy="TREND_LEADER",
            setup="TREND_LEADER",
            entry=100.0,
            stop_loss=95.0,
            take_profit=112.0,
            confidence=0.7,
            evidence_source="paper",
            quote={
                "bid": 99.9,
                "ask": 100.1,
                "last": 100.0,
                "ts_age_seconds": 1,
                "avg_dollar_volume": 5e8,
                "tradable": True,
            },
        ),
        human_approved=True,
    )

    assert result.submitted
    assert result.broker_response["status"] == "filled"
    assert adapter.get_positions()[0]["stop"] == 95.0
    exit_event = adapter.mark_bar("NVDA", high=98.0, low=94.0, close=94.5)
    assert exit_event["reason"] == "stop"
    assert adapter.get_positions() == []
