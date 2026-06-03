#!/usr/bin/env python3
"""Event-driven signal: insider buy clusters + news-flow burst.

Insider clusters (multiple insiders buying within a short window) have one of
the cleanest historical edges in single-stock retail. We also surface a simple
news-flow burst score (count of headlines in last 7d vs. trailing 90d baseline).
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, timedelta
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402


def insider_cluster_score(con, lookback_days: int = 90) -> pd.DataFrame:
    """Score each ticker by recent insider purchase activity.

    Strong signal:  multiple distinct insiders buying in the last 30d,
                    total buy value > $250k, and no offsetting sales.
    """
    df = con.execute(
        """SELECT ticker, insider_name, transaction_date, transaction_code,
                  shares, price_per_share, total_value
           FROM insider_transactions
           WHERE transaction_date >= ?""",
        [date.today() - timedelta(days=lookback_days)]
    ).fetch_df()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "insider_buy_score"])
    df["transaction_date"] = pd.to_datetime(df["transaction_date"]).dt.date

    rows = []
    for ticker, g in df.groupby("ticker"):
        buys = g[g["transaction_code"] == "P"]
        sells = g[g["transaction_code"] == "S"]
        recent_buys = buys[buys["transaction_date"] >= (date.today() - timedelta(days=30))]
        distinct_buyers = recent_buys["insider_name"].nunique()
        buy_value = recent_buys["total_value"].fillna(0).sum()
        sell_value = sells[sells["transaction_date"] >= (date.today() - timedelta(days=30))]["total_value"].fillna(0).sum()
        net = buy_value - sell_value

        # Score components (capped):
        cluster_pts = min(distinct_buyers, 5) * 0.4         # up to 2.0
        size_pts = min(buy_value / 1_000_000, 5)            # up to 5.0 ($5M+)
        net_pts = 1.5 if net > 0 else (-1.0 if net < -1_000_000 else 0)
        score = round(cluster_pts + size_pts + net_pts, 2)

        rows.append({
            "ticker": ticker,
            "insider_buy_score": score,
            "distinct_buyers_30d": int(distinct_buyers),
            "buy_value_30d": float(buy_value),
            "sell_value_30d": float(sell_value),
            "net_30d": float(net),
        })
    return pd.DataFrame(rows).sort_values("insider_buy_score", ascending=False)


def news_burst_score(con) -> pd.DataFrame:
    """Z-score of last-7-day news count vs trailing 90-day baseline."""
    df = con.execute(
        """SELECT ticker, COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL 7 DAY) AS last7,
                  COUNT(*) FILTER (WHERE published_at >= NOW() - INTERVAL 90 DAY) AS last90
           FROM documents
           WHERE ticker IS NOT NULL AND source = 'yahoo_news'
           GROUP BY ticker"""
    ).fetch_df()
    if df.empty:
        return pd.DataFrame(columns=["ticker", "news_burst_score"])
    df["baseline_per_week"] = (df["last90"] / 90) * 7
    df["news_burst_score"] = (df["last7"] - df["baseline_per_week"]).round(2)
    return df[["ticker", "news_burst_score", "last7", "last90"]].sort_values("news_burst_score", ascending=False)


def store_signal(con, sig_date: date, df: pd.DataFrame, signal_name: str, value_col: str):
    rows = []
    df = df.copy()
    df["rank_"] = df[value_col].rank(ascending=False, method="min").astype(int)
    for _, r in df.iterrows():
        rows.append((sig_date, r["ticker"], signal_name, float(r[value_col]), int(r["rank_"]),
                     json.dumps({k: (float(v) if isinstance(v, (int, float)) else v)
                                 for k, v in r.items() if k not in ("ticker", "rank_")})))
    con.executemany(
        """INSERT OR REPLACE INTO signals
           (signal_date, ticker, signal_name, value, rank, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""", rows
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    con = kb()
    insider = insider_cluster_score(con)
    news = news_burst_score(con)
    today = date.today()
    if not insider.empty:
        store_signal(con, today, insider, "insider_buy_cluster", "insider_buy_score")
    if not news.empty:
        store_signal(con, today, news, "news_burst", "news_burst_score")
    con.close()

    if not insider.empty:
        print(f"\nInsider buy cluster — top {args.top}:")
        print(f"{'ticker':<6}  {'score':>6}  {'buyers':>6}  {'buy_value':>12}  {'net':>12}")
        for _, r in insider.head(args.top).iterrows():
            print(f"{r['ticker']:<6}  {r['insider_buy_score']:>6.2f}  {r['distinct_buyers_30d']:>6}  ${r['buy_value_30d']:>11,.0f}  ${r['net_30d']:>11,.0f}")
    else:
        print("No insider transactions in window.")

    if not news.empty:
        print(f"\nNews burst — top {args.top}:")
        for _, r in news.head(args.top).iterrows():
            print(f"  {r['ticker']:<6}  burst={r['news_burst_score']:>6.2f}  last7d={int(r['last7']):>3}  last90d={int(r['last90']):>4}")


if __name__ == "__main__":
    main()
