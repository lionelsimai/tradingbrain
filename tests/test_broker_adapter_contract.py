import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution.broker_base import NullBrokerAdapter, BrokerError, DisabledLiveTradingError, DisabledLiveAdapter
from safety.order import OrderIntent

def test_rejects_unapproved_intent():
    a=NullBrokerAdapter()
    i=OrderIntent(symbol="NVDA",side="buy",strategy="X",client_order_id="c1",qty=1)
    with pytest.raises(BrokerError):
        a.submit(i)

def test_rejects_raw_submit():
    a=NullBrokerAdapter()
    with pytest.raises(BrokerError):
        a.submit_raw("NVDA","buy",1)

def test_live_adapter_disabled():
    with pytest.raises(DisabledLiveTradingError):
        DisabledLiveAdapter()
