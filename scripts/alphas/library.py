"""WorldQuant 101 — selected alphas (Kakushadze 2015, arXiv:1601.00991).

15 alphas with average pairwise correlation ~16% (orthogonal-ish).
Each alpha takes a panel DataFrame (MultiIndex: date, ticker) with columns
open, high, low, close, volume and returns a Series of scores indexed
the same way. Higher score = more bullish.

Numbering follows the original paper. Industry-neutralised alphas are
adapted to use sector from the universe yaml.
"""
from __future__ import annotations
import numpy as np
import pandas as pd

# --- small operators reused across alphas -------------------------------

def _rank(s: pd.Series) -> pd.Series:
    """Cross-sectional rank within each date, scaled to [0,1]."""
    return s.groupby(level="date").rank(pct=True)

def _ts(s: pd.Series, w: int, fn):
    return s.groupby(level="ticker").transform(lambda x: fn(x.rolling(w)))

def _delta(s: pd.Series, w: int) -> pd.Series:
    return s.groupby(level="ticker").transform(lambda x: x.diff(w))

def _ts_rank(s: pd.Series, w: int) -> pd.Series:
    return _ts(s, w, lambda r: r.rank(pct=True))

def _ts_mean(s, w): return _ts(s, w, lambda r: r.mean())
def _ts_std(s, w):  return _ts(s, w, lambda r: r.std())
def _ts_max(s, w):  return _ts(s, w, lambda r: r.max())
def _ts_min(s, w):  return _ts(s, w, lambda r: r.min())
def _ts_sum(s, w):  return _ts(s, w, lambda r: r.sum())

def _corr(a: pd.Series, b: pd.Series, w: int) -> pd.Series:
    df = pd.concat({"a": a, "b": b}, axis=1).sort_index()
    def _one(g):
        return g["a"].rolling(w).corr(g["b"])
    return df.groupby(level="ticker", group_keys=False).apply(_one)

# --- the 15 selected alphas ---------------------------------------------

def alpha_1(df):
    """rank(arg_max(stddev(ret, 20) if ret<0 else close)^2, 5)) - 0.5"""
    r = df["close"].groupby(level="ticker").pct_change()
    s = pd.Series(np.where(r < 0, _ts_std(r, 20).fillna(0), df["close"]) ** 2,
                  index=df.index)
    return _rank(s) - 0.5

def alpha_3(df):
    """-correlation(rank(open), rank(volume), 10)"""
    return -_corr(_rank(df["open"]), _rank(df["volume"]), 10)

def alpha_4(df):
    """-Ts_Rank(rank(low), 9)"""
    return -_ts_rank(_rank(df["low"]), 9)

def alpha_5(df):
    """Simplified: rank(open - sma(close, 10)) * (-1 * abs(rank(close - sma(close, 10))))"""
    sma = _ts_mean(df["close"], 10)
    return _rank(df["open"] - sma) * (-1 * _rank(df["close"] - sma).abs())

def alpha_6(df):
    """-correlation(open, volume, 10)"""
    return -_corr(df["open"], df["volume"], 10)

def alpha_12(df):
    """sign(delta(volume, 1)) * (-delta(close, 1))"""
    return np.sign(_delta(df["volume"], 1)) * (-_delta(df["close"], 1))

def alpha_14(df):
    """-rank(delta(returns, 3)) * correlation(open, volume, 10)"""
    r = df["close"].groupby(level="ticker").pct_change()
    return -_rank(_delta(r, 3)) * _corr(df["open"], df["volume"], 10)

def alpha_23(df):
    """if sma(high, 20) < high then -delta(high, 2) else 0"""
    return pd.Series(
        np.where(_ts_mean(df["high"], 20) < df["high"], -_delta(df["high"], 2), 0),
        index=df.index,
    )

def alpha_26(df):
    """-ts_max(correlation(ts_rank(volume,5), ts_rank(high,5), 5), 3)"""
    c = _corr(_ts_rank(df["volume"], 5), _ts_rank(df["high"], 5), 5)
    return -_ts_max(c, 3)

def alpha_41(df):
    """((high*low)^0.5) - close   (using close as VWAP proxy)"""
    return (df["high"] * df["low"]).pow(0.5) - df["close"]

def alpha_43(df):
    """ts_rank(volume / adv20, 20) * ts_rank(-delta(close, 7), 8)"""
    adv20 = _ts_mean(df["volume"], 20)
    return _ts_rank(df["volume"] / adv20, 20) * _ts_rank(-_delta(df["close"], 7), 8)

def alpha_53(df):
    """-delta((close - low) - (high - close)) / (close - low), 9)"""
    num = (df["close"] - df["low"]) - (df["high"] - df["close"])
    return -_delta(num / (df["close"] - df["low"] + 1e-9), 9)

def alpha_54(df):
    """-(low - close)*(open^5) / ((low - high)*(close^5))"""
    return -((df["low"] - df["close"]) * df["open"].pow(5)) / (
        (df["low"] - df["high"]) * df["close"].pow(5) + 1e-9
    )

def alpha_84(df):
    """sign(delta(close,5)) * rank(ts_rank(close,15))"""
    return np.sign(_delta(df["close"], 5)) * _rank(_ts_rank(df["close"], 15))

def alpha_101(df):
    """(close - open) / ((high - low) + 0.001)  — daily efficiency"""
    return (df["close"] - df["open"]) / (df["high"] - df["low"] + 0.001)

ALPHAS = {
    "wq001": alpha_1,   "wq003": alpha_3,   "wq004": alpha_4,
    "wq005": alpha_5,   "wq006": alpha_6,   "wq012": alpha_12,
    "wq014": alpha_14,  "wq023": alpha_23,  "wq026": alpha_26,
    "wq041": alpha_41,  "wq043": alpha_43,  "wq053": alpha_53,
    "wq054": alpha_54,  "wq084": alpha_84,  "wq101": alpha_101,
}
