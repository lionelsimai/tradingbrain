#!/usr/bin/env python3
"""Walk-forward OOS backtest. 6 rolling windows, train on first 70 percent, test next 30 percent.

Anti-overfitting guard. Compares OOS Sharpe vs in-sample to flag p-hacking.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import duckdb, numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"


def daily_returns():
    con = duckdb.connect(str(PRICES), read_only=True)
    px = con.execute("SELECT date, ticker, close FROM prices ORDER BY ticker, date").fetchdf()
    px["date"] = pd.to_datetime(px["date"])
    wide = px.pivot(index="date", columns="ticker", values="close")
    return wide.pct_change().fillna(0)


def momentum_signal(returns: pd.DataFrame, lookback: int = 90) -> pd.Series:
    """Top-decile cumulative return over lookback. Returns weights at the LAST date."""
    cum = (1 + returns).cumprod()
    mom = cum.iloc[-1] / cum.iloc[max(0, len(cum)-lookback-1)] - 1
    mom = mom.dropna()
    threshold = mom.quantile(0.85)
    w = (mom >= threshold).astype(float)
    s = w.sum()
    return (w / s) if s > 0 else w


def perf(returns: pd.Series) -> dict:
    if returns.empty or returns.std() == 0:
        return {"sharpe": 0.0, "cagr": 0.0, "maxdd": 0.0, "n_days": len(returns)}
    sharpe = (returns.mean() / returns.std()) * np.sqrt(252)
    cum = (1 + returns).cumprod()
    cagr = (cum.iloc[-1] ** (252 / max(1, len(returns)))) - 1
    dd = (cum / cum.cummax() - 1).min()
    return {"sharpe": round(float(sharpe), 2), "cagr": round(float(cagr), 4),
            "maxdd": round(float(dd), 4), "n_days": len(returns)}


def main():
    rets = daily_returns()
    n = len(rets)
    if n < 200:
        print("not enough history for walk-forward")
        sys.exit(1)

    n_windows = 6
    window = n // (n_windows + 1)
    rows = []
    for i in range(n_windows):
        start = i * window
        train_end = start + int(window * 0.7)
        test_end = min(n, start + window + int(window * 0.3))
        train = rets.iloc[start:train_end]
        test = rets.iloc[train_end:test_end]
        if len(test) < 20:
            continue
        w = momentum_signal(train)
        strat_test = (test.fillna(0) * w.reindex(test.columns, fill_value=0)).sum(axis=1)
        in_sample_test_returns = (train.iloc[-len(train)//4:].fillna(0) * w.reindex(train.columns, fill_value=0)).sum(axis=1)
        is_perf = perf(in_sample_test_returns)
        oos_perf = perf(strat_test)
        spy_perf = perf(test["SPY"])
        rows.append({
            "window": i + 1,
            "train_period": f"{train.index[0].date()} -> {train.index[-1].date()}",
            "test_period": f"{test.index[0].date()} -> {test.index[-1].date()}",
            "in_sample_sharpe": is_perf["sharpe"],
            "oos_sharpe": oos_perf["sharpe"],
            "oos_cagr": oos_perf["cagr"],
            "oos_maxdd": oos_perf["maxdd"],
            "spy_sharpe": spy_perf["sharpe"],
            "spy_cagr": spy_perf["cagr"],
            "alpha_cagr": round(oos_perf["cagr"] - spy_perf["cagr"], 4),
        })

    df = pd.DataFrame(rows)
    print("Walk-forward OOS backtest (top-decile 90d momentum, equal-weight):")
    print(df.to_string(index=False))
    summary = {
        "windows": len(df),
        "median_oos_sharpe": round(float(df["oos_sharpe"].median()), 2),
        "median_oos_cagr": round(float(df["oos_cagr"].median()), 4),
        "median_alpha_cagr": round(float(df["alpha_cagr"].median()), 4),
        "is_vs_oos_gap": round(float(df["in_sample_sharpe"].median() - df["oos_sharpe"].median()), 2),
        "windows_beating_spy": int((df["alpha_cagr"] > 0).sum()),
        "rows": rows,
    }
    print(f"\nMedian OOS Sharpe: {summary['median_oos_sharpe']}")
    print(f"Median OOS alpha vs SPY: {summary['median_alpha_cagr']:+.2%}")
    print(f"In-sample vs OOS Sharpe gap: {summary['is_vs_oos_gap']:+.2f}  (small = honest)")
    print(f"Windows beating SPY: {summary['windows_beating_spy']}/{len(df)}")
    out = ROOT / "reports" / "walk-forward.json"
    out.write_text(json.dumps(summary, indent=2))
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
