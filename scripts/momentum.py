#!/usr/bin/env python3
"""Clenow-style momentum ranking with regime + trend filters.

For each ticker in the universe:
  1. Fit log-price linear regression over the last 90 trading days
  2. Annualised slope = (exp(slope * 252) - 1) * 100
  3. Score = annualised_slope * R^2
  4. Filter: must be above 100-day MA, no >15% single-day jump in last 90d
  5. Regime: SPY must be above 200-day MA; otherwise show all but warn cash-only

Outputs JSON to stdout (or --out path); also writes the latest snapshot
to data/momentum.parquet so the dashboard + digest can read it cheaply.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import duckdb, numpy as np, pandas as pd

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
DB = ROOT / "data" / "prices.duckdb"
OUT_PARQUET = ROOT / "data" / "momentum.parquet"

LOOKBACK = 90        # trading days for regression
TREND_MA = 100       # days for trend filter
REGIME_MA = 200      # days for regime filter (SPY)
GAP_THRESHOLD = 0.15 # 15% single-day jump disqualifies
ATR_DAYS = 20        # for vol-weighted sizing

def fetch_prices(con, ticker: str, n_days: int) -> pd.DataFrame:
    return con.execute(
        "SELECT date, close, adj_close, high, low FROM prices "
        "WHERE ticker = ? ORDER BY date DESC LIMIT ?",
        [ticker, n_days],
    ).fetch_df().iloc[::-1].reset_index(drop=True)

def clenow_score(closes: np.ndarray) -> tuple[float, float, float]:
    if len(closes) < LOOKBACK:
        return float("nan"), float("nan"), float("nan")
    y = np.log(closes[-LOOKBACK:])
    x = np.arange(LOOKBACK, dtype=float)
    slope, intercept = np.polyfit(x, y, 1)
    y_pred = slope * x + intercept
    ss_res = np.sum((y - y_pred) ** 2)
    ss_tot = np.sum((y - y.mean()) ** 2)
    r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
    ann = (math.exp(slope * 252) - 1) * 100
    return ann, r2, ann * r2

def atr(df: pd.DataFrame, n: int = ATR_DAYS) -> float:
    if len(df) < n + 1:
        return float("nan")
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum.reduce([h - l, np.abs(h - prev_c), np.abs(l - prev_c)])
    return float(np.mean(tr[-n:]))

def trend_ok(closes: np.ndarray, ma_days: int = TREND_MA) -> bool:
    if len(closes) < ma_days:
        return False
    return bool(closes[-1] > np.mean(closes[-ma_days:]))

def no_big_gap(closes: np.ndarray) -> bool:
    if len(closes) < LOOKBACK + 1:
        return True
    window = closes[-(LOOKBACK + 1):]
    returns = np.diff(window) / window[:-1]
    return bool(np.max(np.abs(returns)) < GAP_THRESHOLD)

def regime_state(con) -> dict:
    df = fetch_prices(con, "SPY", REGIME_MA + 20)
    if len(df) < REGIME_MA:
        return {"ok": False, "spy_close": None, "spy_ma200": None, "reason": "insufficient SPY history"}
    closes = df["adj_close"].values
    ma200 = float(np.mean(closes[-REGIME_MA:]))
    return {
        "ok": bool(closes[-1] > ma200),
        "spy_close": float(closes[-1]),
        "spy_ma200": ma200,
        "spy_above_ma200_pct": float((closes[-1] / ma200 - 1) * 100),
        "as_of": str(df["date"].iloc[-1]),
    }

def rank_universe():
    con = duckdb.connect(str(DB))
    tickers = [r[0] for r in con.execute(
        "SELECT ticker FROM universe WHERE category != 'benchmark' ORDER BY ticker"
    ).fetchall()]
    regime = regime_state(con)
    rows: list[dict] = []
    for t in tickers:
        df = fetch_prices(con, t, max(TREND_MA, LOOKBACK) + 10)
        if df.empty or len(df) < LOOKBACK:
            continue
        closes = df["adj_close"].values
        ann, r2, score = clenow_score(closes)
        rows.append({
            "ticker": t,
            "score": round(score, 2) if not math.isnan(score) else None,
            "ann_slope_pct": round(ann, 2),
            "r2": round(r2, 3),
            "close": float(closes[-1]),
            "trend_ok": trend_ok(closes),
            "no_big_gap": no_big_gap(closes),
            "atr20": round(atr(df), 4),
            "atr_pct": round(atr(df) / closes[-1] * 100, 2) if closes[-1] > 0 else None,
        })
    con.close()
    df = pd.DataFrame(rows).sort_values("score", ascending=False).reset_index(drop=True)
    df["passes_filters"] = df["trend_ok"] & df["no_big_gap"]
    df["rank"] = df["score"].rank(method="min", ascending=False).astype(int)
    df.to_parquet(OUT_PARQUET)
    return regime, df

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="Optional JSON output path")
    ap.add_argument("--top", type=int, default=15, help="Print top N")
    a = ap.parse_args()
    regime, df = rank_universe()
    payload = {
        "regime": regime,
        "as_of": str(df.iloc[0].to_dict() if not df.empty else None),
        "ranked": df.to_dict(orient="records"),
    }
    if a.out:
        Path(a.out).write_text(json.dumps(payload, indent=2, default=str))
    print(f"REGIME: {'BULL' if regime['ok'] else 'CASH'}  SPY {regime['spy_close']:.2f} vs MA200 {regime['spy_ma200']:.2f} ({regime['spy_above_ma200_pct']:+.2f}%)")
    print()
    print(f"{'rank':>4}  {'ticker':<6}  {'score':>8}  {'ann%':>7}  {'r2':>5}  {'ATR%':>5}  {'pass':<5}")
    for _, r in df.head(a.top).iterrows():
        flag = "yes" if r["passes_filters"] else "no"
        print(f"  {r['rank']:>3}  {r['ticker']:<6}  {r['score']:>8.2f}  {r['ann_slope_pct']:>7.2f}  {r['r2']:>5.3f}  {r['atr_pct']:>5.2f}  {flag}")

if __name__ == "__main__":
    main()
