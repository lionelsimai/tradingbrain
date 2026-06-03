import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety.order import Order, OrderIntent

def test_deterministic_idempotency():
    a = Order(symbol="NVDA", side="buy", strategy="X")
    b = Order(symbol="NVDA", side="buy", strategy="X")
    assert a.client_order_id == b.client_order_id

def test_different_inputs_differ():
    a = Order(symbol="NVDA", side="buy", strategy="X")
    b = Order(symbol="AMD", side="buy", strategy="X")
    assert a.client_order_id != b.client_order_id

def test_intent_alias():
    assert OrderIntent is Order

def test_approval_defaults_false():
    assert Order(symbol="X", side="buy", strategy="Y").approved_by_risk is False
