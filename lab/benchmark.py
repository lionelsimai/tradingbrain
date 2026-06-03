#!/usr/bin/env python3
"""Honest benchmarking. A momentum strategy on AI mega-caps must NOT be scored
against SPY — that flatters it. The right bar is what you'd get by simply
holding the same universe (equal-weight basket) or its obvious index proxy (QQQ).

Computes, for a strategy daily-return series vs a benchmark:
  total/CAGR, Sharpe, Sortino, max drawdown, beta, annualized alpha (CAPM),
  information ratio, and tracking error.

CLI: python3 -m lab.benchmark --curve reports/backtest-<...>.csv
     (the equity-curve CSV that backtest/engine.py writes: columns date,equity)
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
import pandas as pd
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
TRADING_DAYS = 252


def _series(ticker: str) -> pd.Series:
    con = duckdb.connect(str(PRICES), read_only=True)
    df = con.execute(
        "SELECT date, adj_close FROM prices WHERE ticker=? ORDER BY date", [ticker]).fetchdf()
    con.close()
    if df.empty:
        return pd.Series(dtype=float)
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["adj_close"]


def equal_weight_basket(start, end) -> pd.Series:
    """Daily equal-weight (rebalanced) total-return proxy of the whole universe."""
    con = duckdb.connect(str(PRICES), read_only=True)
    df = con.execute(
        "SELECT date,ticker,adj_close FROM prices WHERE ticker NOT IN ('SPY','QQQ','SMH','^GSPC') "
        "AND date BETWEEN ? AND ? ORDER BY date", [str(start), str(end)]).fetchdf()
    con.close()
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="ticker", values="adj_close")
    rets = wide.pct_change()
    ew = rets.mean(axis=1, skipna=True)          # equal weight, ignore missing
    return (1 + ew.fillna(0)).cumprod()


def perf_stats(returns: pd.Series) -> dict:
    r = returns.dropna()
    if len(r) < 5:
        return {}
    eq = (1 + r).cumprod()
    yrs = len(r) / TRADING_DAYS
    cagr = eq.iloc[-1] ** (1 / yrs) - 1 if yrs > 0 else 0.0
    sharpe = (r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() > 0 else 0.0
    downside = r[r < 0].std()
    sortino = (r.mean() / downside * np.sqrt(TRADING_DAYS)) if downside and downside > 0 else 0.0
    dd = (eq / eq.cummax() - 1).min()
    return {
        "total_return_pct": round(float(eq.iloc[-1] - 1) * 100, 2),
        "cagr_pct": round(float(cagr) * 100, 2),
        "sharpe": round(float(sharpe), 2),
        "sortino": round(float(sortino), 2),
        "max_drawdown_pct": round(float(dd) * 100, 1),
    }


def vs_benchmark(strat_ret: pd.Series, bench_ret: pd.Series) -> dict:
    df = pd.concat([strat_ret.rename("s"), bench_ret.rename("b")], axis=1).dropna()
    if len(df) < 10:
        return {}
    s, b = df["s"].values, df["b"].values
    var_b = np.var(b, ddof=1)
    beta = float(np.cov(s, b, ddof=1)[0, 1] / var_b) if var_b > 0 else 0.0
    alpha_daily = s.mean() - beta * b.mean()
    active = s - b
    te = active.std(ddof=1)
    ir = float(active.mean() / te * np.sqrt(TRADING_DAYS)) if te > 0 else 0.0
    return {
        "beta": round(beta, 2),
        "alpha_annual_pct": round(float(alpha_daily) * TRADING_DAYS * 100, 2),
        "information_ratio": round(ir, 2),
        "tracking_error_annual_pct": round(float(te * np.sqrt(TRADING_DAYS) * 100), 2),
        "excess_return_pct": round(float(((1 + active).prod() - 1)) * 100, 2),
    }


def evaluate(curve_csv: str) -> dict:
    eq = pd.read_csv(curve_csv)
    date_col = "date" if "date" in eq.columns else eq.columns[0]
    eq_col = "equity" if "equity" in eq.columns else eq.columns[-1]
    eq[date_col] = pd.to_datetime(eq[date_col])
    eq = eq.set_index(date_col).sort_index()
    strat_ret = eq[eq_col].pct_change().dropna()
    start, end = strat_ret.index.min().date(), strat_ret.index.max().date()

    out = {"period": [str(start), str(end)], "strategy": perf_stats(strat_ret), "benchmarks": {}}
    for name, ser in [("QQQ", _series("QQQ")), ("SPY", _series("SPY")),
                      ("equal_weight_basket", equal_weight_basket(start, end))]:
        if ser.empty:
            continue
        bret = ser.pct_change().reindex(strat_ret.index).dropna()
        bp = perf_stats(bret)
        rel = vs_benchmark(strat_ret, bret)
        out["benchmarks"][name] = {**bp, **rel}
    # headline verdict vs the demanding benchmark (basket, else QQQ)
    key = "equal_weight_basket" if "equal_weight_basket" in out["benchmarks"] else "QQQ"
    if key in out["benchmarks"]:
        bm = out["benchmarks"][key]
        s = out["strategy"]
        out["verdict"] = (
            f"vs {key}: strategy Sharpe {s.get('sharpe')} vs {bm.get('sharpe')}, "
            f"alpha {bm.get('alpha_annual_pct')}%/yr, IR {bm.get('information_ratio')}, "
            f"beta {bm.get('beta')}. "
            + ("Adds risk-adjusted value." if (s.get('sharpe', 0) >= bm.get('sharpe', 0)
               or bm.get('information_ratio', 0) > 0.3)
               else "Does NOT beat simply holding the basket on a risk-adjusted basis."))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--curve", required=True, help="equity-curve CSV from backtest/engine.py")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = evaluate(a.curve)
    import json
    if a.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Period {res['period'][0]} → {res['period'][1]}")
        print(f"  STRATEGY: {res['strategy']}")
        for name, b in res["benchmarks"].items():
            print(f"  {name:20}: {b}")
        print(f"\n  {res.get('verdict','')}")


if __name__ == "__main__":
    main()
