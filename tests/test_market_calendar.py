import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import market_calendar as mc

def test_weekend_closed():
    assert not mc.is_trading_day(date(2026,5,30))  # Saturday

def test_weekday_open():
    assert mc.is_trading_day(date(2026,5,29))  # Friday

def test_holiday_closed():
    assert not mc.is_trading_day(date(2026,1,1))  # New Year

def test_session_label():
    assert mc.session() in ("regular","premarket","afterhours","closed")
