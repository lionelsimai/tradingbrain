import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import quote_validator as qv

def _q(**k):
    base = dict(bid=212.5, ask=212.8, last=212.65, ts_age_seconds=2,
                avg_dollar_volume=5e8, market_session="regular", tradable=True)
    base.update(k); return base

def test_good_quote_passes():
    assert qv.validate(_q(), intraday=True, require_market_open=False).ok

def test_stale_rejected():
    assert not qv.validate(_q(ts_age_seconds=99999), intraday=True, require_market_open=False).ok

def test_wide_spread_rejected():
    assert not qv.validate(_q(bid=100, ask=130), intraday=True, require_market_open=False).ok

def test_missing_bid_rejected():
    assert not qv.validate(_q(bid=None), intraday=True, require_market_open=False).ok

def test_untradable_rejected():
    assert not qv.validate(_q(tradable=False), intraday=True, require_market_open=False).ok
