from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.ingest import moomoo


def test_moomoo_code_defaults_to_us_market():
    assert moomoo.moomoo_code("nvda") == "US.NVDA"
    assert moomoo.moomoo_code("US.MU") == "US.MU"
    assert moomoo.plain_ticker("US.AMD") == "AMD"


def test_snapshot_to_frame_writes_intraday_shape():
    raw = pd.DataFrame([{
        "code": "US.NVDA",
        "update_time": "2026-06-02 10:42:00",
        "last_price": 227.39,
        "prev_close_price": 211.13,
        "bid_price": 227.38,
        "ask_price": 227.4,
        "bid_vol": 100,
        "ask_vol": 200,
        "sec_status": "NORMAL",
    }])

    df = moomoo.snapshot_to_frame(raw, {}, datetime(2026, 6, 2, 14, 42, tzinfo=timezone.utc))

    assert list(df["ticker"]) == ["NVDA"]
    assert df.loc[0, "source"] == "moomoo:market_snapshot"
    assert df.loc[0, "bid"] == 227.38
    assert df.loc[0, "ask"] == 227.4
    assert df.loc[0, "market_state"] == "REGULAR"
    assert df.loc[0, "change_pct"] > 0


def test_moomoo_refuses_live_execution_flags(monkeypatch):
    monkeypatch.setenv("TB_MODE", "live")
    monkeypatch.setenv("TB_ALLOW_LIVE", "1")

    with pytest.raises(SystemExit, match="Refusing to run"):
        moomoo.main([])
