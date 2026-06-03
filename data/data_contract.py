#!/usr/bin/env python3
"""OHLCV frame contract. Reconstructed to satisfy tests/test_data_contract.py.
validate_frame(df) -> {"ok": bool, "problems": [...]}. Rejects missing columns,
negative prices, and OHLC inversions. (pandas imported here only — data/__init__
stays import-light so the order path never needs pandas.)
"""
from __future__ import annotations

REQUIRED = ["date", "open", "high", "low", "close", "volume"]
_PRICE = ["open", "high", "low", "close"]


def validate_frame(df) -> dict:
    problems: list = []
    try:
        cols = set(df.columns)
    except Exception:
        return {"ok": False, "problems": ["not a dataframe"]}

    missing = [c for c in REQUIRED if c not in cols]
    if missing:
        problems.append(f"missing columns: {missing}")
        return {"ok": False, "problems": problems}

    if len(df) == 0:
        problems.append("empty frame")
        return {"ok": False, "problems": problems}

    # negative / non-positive prices
    for c in _PRICE:
        if (df[c] < 0).any():
            problems.append(f"negative values in {c}")
        if (df[c] <= 0).any():
            problems.append(f"non-positive prices in {c}")
    if (df["volume"] < 0).any():
        problems.append("negative volume")

    # OHLC inversions: high must be the max, low the min of the bar
    bar_max = df[["open", "close", "low"]].max(axis=1)
    bar_min = df[["open", "close", "high"]].min(axis=1)
    if (df["high"] < bar_max).any():
        problems.append("high below open/close/low (inversion)")
    if (df["low"] > bar_min).any():
        problems.append("low above open/close/high (inversion)")

    return {"ok": len(problems) == 0, "problems": problems}
