#!/usr/bin/env python3
"""US (NYSE) trading calendar + session label. Reconstructed to satisfy
tests/test_market_calendar.py and caller usage (execution/paper_adapter.py:71,
scripts/paper_trade.py:67). Most tests monkeypatch session(); is_trading_day()
must close weekends + NYSE holidays.
"""
from __future__ import annotations
from datetime import date, datetime, timedelta
from functools import lru_cache

try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:  # pragma: no cover
    _ET = None


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th weekday (0=Mon) of month. n<0 counts from the end."""
    if n > 0:
        d = date(year, month, 1)
        offset = (weekday - d.weekday()) % 7
        return d + timedelta(days=offset + 7 * (n - 1))
    # last weekday of the month
    if month == 12:
        d = date(year, 12, 31)
    else:
        d = date(year, month + 1, 1) - timedelta(days=1)
    offset = (d.weekday() - weekday) % 7
    return d - timedelta(days=offset)


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm (for Good Friday)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def _observed(d: date) -> date:
    """NYSE observance: Sat holiday -> Fri before; Sun holiday -> Mon after."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache(maxsize=32)
def _holidays(year: int) -> frozenset:
    h = {
        _observed(date(year, 1, 1)),                    # New Year's Day
        _nth_weekday(year, 1, 0, 3),                    # MLK Day (3rd Mon Jan)
        _nth_weekday(year, 2, 0, 3),                    # Presidents' Day (3rd Mon Feb)
        _easter(year) - timedelta(days=2),              # Good Friday
        _nth_weekday(year, 5, 0, -1),                   # Memorial Day (last Mon May)
        _observed(date(year, 6, 19)),                   # Juneteenth
        _observed(date(year, 7, 4)),                    # Independence Day
        _nth_weekday(year, 9, 0, 1),                    # Labor Day (1st Mon Sep)
        _nth_weekday(year, 11, 3, 4),                   # Thanksgiving (4th Thu Nov)
        _observed(date(year, 12, 25)),                  # Christmas
    }
    return frozenset(h)


def is_trading_day(d: date | None = None) -> bool:
    if d is None:
        d = now().date()
    if isinstance(d, datetime):
        d = d.date()
    if d.weekday() >= 5:               # Sat/Sun
        return False
    return d not in _holidays(d.year)


def now() -> datetime:
    return datetime.now(_ET) if _ET else datetime.now()


def session(now_dt: datetime | None = None) -> str:
    """One of: regular | premarket | afterhours | closed."""
    n = now_dt or now()
    if _ET is not None and n.tzinfo is None:
        n = n.replace(tzinfo=_ET)
    if not is_trading_day(n.date()):
        return "closed"
    minutes = n.hour * 60 + n.minute
    if 4 * 60 <= minutes < 9 * 60 + 30:
        return "premarket"
    if 9 * 60 + 30 <= minutes < 16 * 60:
        return "regular"
    if 16 * 60 <= minutes < 20 * 60:
        return "afterhours"
    return "closed"
