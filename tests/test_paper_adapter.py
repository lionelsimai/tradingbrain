import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution.paper_adapter import PaperAdapter
from safety.order import OrderIntent

def _a():
    a=PaperAdapter(equity=50000)
    a.set_quote("NVDA",bid=212.5,ask=212.8,last=212.65,age_s=2)
    return a

def test_fill_with_slippage():
    a=_a()
    i=OrderIntent(symbol="NVDA",side="buy",strategy="X",client_order_id="c1",
                  qty=40,order_type="limit",limit_price=213,stop_loss=206,
                  take_profit=236,approved_by_risk=True)
    r=a._place(i)
    assert r["status"] in ("filled","partially_filled")
    assert r["avg_price"] > 212.8  # paid ask+slippage

def test_stale_quote_rejected():
    a=PaperAdapter(equity=50000); a.set_quote("NVDA",212.5,212.8,212.65,age_s=99999)
    i=OrderIntent(symbol="NVDA",side="buy",strategy="X",client_order_id="c2",qty=10,
                  stop_loss=206,approved_by_risk=True)
    assert a._place(i)["status"]=="rejected"

def test_gap_through_stop():
    a=_a()
    i=OrderIntent(symbol="NVDA",side="buy",strategy="X",client_order_id="c3",qty=10,
                  stop_loss=206,take_profit=236,approved_by_risk=True)
    a._place(i)
    out=a.mark_bar("NVDA",high=210,low=204,close=205)
    assert out and out["reason"]=="stop"
