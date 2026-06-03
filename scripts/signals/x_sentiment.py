#!/usr/bin/env python3
"""X (Twitter) sentiment signal.

Reads from `documents` where source starts with 'x:'. Each X document has:
  - title:   short snippet of the post
  - content: full text
  - meta_json: {ticker, handle, retweets, likes, sentiment, posted_at}

The daily-digest agent populates these by calling x_search with curated
FinTwit handles. This script scores each ticker by:

  - volume_z      : how much chatter vs baseline (last 7d vs trailing 60d)
  - sentiment_avg : mean of meta_json.sentiment over last 7d   (-1 .. +1)
  - engagement    : log-weighted likes+retweets
  - composite     : 0.5 * sentiment_avg + 0.3 * tanh(volume_z) + 0.2 * tanh(engagement_z)

Output: one row per ticker per day in `signals` (kind='x_sentiment').
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, timedelta
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb  # noqa: E402


def fetch_x_docs(con, lookback_days: int = 60) -> pd.DataFrame:
    cutoff = date.today() - timedelta(days=lookback_days)
    rows = con.execute(
        """SELECT doc_id, source, title, body, metadata, ticker, ingested_at
           FROM documents
           WHERE source LIKE 'x:%' AND ingested_at >= ?""",
        [cutoff],
    ).fetchdf()
    if rows.empty:
        return rows
    # parse meta json
    def parse(s):
        try: return json.loads(s) if s else {}
        except Exception: return {}
    meta = rows["metadata"].apply(parse)
    rows["ticker"] = meta.apply(lambda m: m.get("ticker")) .fillna(rows["ticker"])
    rows["sentiment"] = meta.apply(lambda m: m.get("sentiment", 0.0)).astype(float)
    rows["likes"] = meta.apply(lambda m: m.get("likes", 0)).astype(float)
    rows["retweets"] = meta.apply(lambda m: m.get("retweets", 0)).astype(float)
    rows["handle"] = meta.apply(lambda m: m.get("handle"))
    rows["posted_at"] = pd.to_datetime(
        meta.apply(lambda m: m.get("posted_at")), errors="coerce", utc=True
    ).fillna(pd.to_datetime(rows["ingested_at"], utc=True))
    rows = rows.dropna(subset=["ticker"])
    return rows


def score(rows: pd.DataFrame, today: date) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=["ticker", "volume_z", "sentiment_avg",
                                     "engagement_z", "composite"])
    rows["age_days"] = (pd.Timestamp(today, tz="UTC") - rows["posted_at"]).dt.days
    recent = rows[rows["age_days"] <= 7]
    baseline = rows[(rows["age_days"] > 7) & (rows["age_days"] <= 60)]

    counts_recent = recent.groupby("ticker").size().rename("n_recent")
    counts_base = baseline.groupby("ticker").size().rename("n_base")
    sent_recent = recent.groupby("ticker")["sentiment"].mean().rename("sentiment_avg")
    eng_recent = (
        recent.assign(eng=lambda d: np.log1p(d["likes"] + 2 * d["retweets"]))
        .groupby("ticker")["eng"].mean().rename("engagement_avg")
    )
    df = pd.concat([counts_recent, counts_base, sent_recent, eng_recent], axis=1).fillna(0.0)
    # daily-rate baseline (7d vs 53d)
    df["rate_recent"] = df["n_recent"] / 7.0
    df["rate_base"] = df["n_base"] / 53.0
    df["volume_z"] = np.where(
        df["rate_base"] > 0,
        (df["rate_recent"] - df["rate_base"]) / (df["rate_base"] + 0.5),
        df["rate_recent"],
    )
    df["engagement_z"] = (df["engagement_avg"] - df["engagement_avg"].mean()) / (
        df["engagement_avg"].std() + 1e-9
    )
    df["composite"] = (
        0.5 * df["sentiment_avg"]
        + 0.3 * np.tanh(df["volume_z"])
        + 0.2 * np.tanh(df["engagement_z"])
    )
    return df.reset_index()[["ticker", "volume_z", "sentiment_avg",
                              "engagement_z", "composite"]]


def write_signals(con, df: pd.DataFrame, asof: date):
    if df.empty:
        return 0
    df = df.sort_values("composite", ascending=False).reset_index(drop=True)
    rows = []
    for i, c in df.iterrows():
        rows.append((
            asof, c["ticker"], "x_sentiment",
            float(c["composite"]), int(i) + 1,
            json.dumps({k: float(c[k]) for k in
                        ["volume_z", "sentiment_avg", "engagement_z", "composite"]}),
        ))
    con.execute("DELETE FROM signals WHERE signal_date = ? AND signal_name = 'x_sentiment'", [asof])
    con.executemany(
        """INSERT OR REPLACE INTO signals
           (signal_date, ticker, signal_name, value, rank, metadata)
           VALUES (?, ?, ?, ?, ?, ?)""", rows,
    )
    return len(rows)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args(argv)
    con = kb()
    rows = fetch_x_docs(con)
    today = date.today()
    df = score(rows, today)
    n = write_signals(con, df, today)
    if df.empty:
        print("X sentiment: no X documents yet. The daily agent populates these.")
        print("Stub row will be inserted when X docs arrive.")
        return
    df = df.sort_values("composite", ascending=False)
    print(f"\nX sentiment — top {a.show}:")
    print(df.head(a.show).to_string(index=False,
        formatters={"volume_z": "{:+.2f}".format,
                    "sentiment_avg": "{:+.2f}".format,
                    "engagement_z": "{:+.2f}".format,
                    "composite": "{:+.2f}".format}))
    print(f"\n{n} rows written to signals (kind='x_sentiment').")


if __name__ == "__main__":
    main()
