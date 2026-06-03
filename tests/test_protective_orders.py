from execution import protective_orders
from execution.paper_adapter import PaperAdapter, PaperConfig
from safety.order import Order


def test_reject_entry_without_stop():
    order = Order(symbol="NVDA", side="buy", strategy="X", limit_price=100.0,
                  stop_loss=None, take_profit=112.0, approved_by_risk=True)

    assert "missing stop loss" in protective_orders.require_protective(order)


def test_reject_long_stop_above_entry():
    order = Order(symbol="NVDA", side="buy", strategy="X", limit_price=100.0,
                  stop_loss=101.0, take_profit=112.0, approved_by_risk=True)

    assert "long stop must be below entry" in protective_orders.require_protective(order)


def test_reject_no_target_or_trailing_policy():
    order = Order(symbol="NVDA", side="buy", strategy="X", limit_price=100.0,
                  stop_loss=95.0, take_profit=None, approved_by_risk=True)

    assert "missing target or trailing-exit policy" in protective_orders.require_protective(order)


def test_attach_detects_filled_position_without_stop():
    adapter = PaperAdapter(cfg=PaperConfig(partial_fill_prob=0.0, seed=7))
    adapter._positions["NVDA"] = {"symbol": "NVDA", "qty": 1, "entry": 100.0, "stop": None, "target": 112.0}
    order = Order(symbol="NVDA", side="buy", strategy="X", limit_price=100.0,
                  stop_loss=95.0, take_profit=112.0, approved_by_risk=True)

    result = protective_orders.attach(adapter, order)

    assert result["incident"] is True
    assert "filled entry without active stop" in result["reasons"]
