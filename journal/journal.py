#!/usr/bin/env python3
"""Forecast journal — track your forecasts vs reality, grade calibration.

Two commands:
  python3 -m journal.journal forecast NVDA --direction UP --horizon 30 --prob 0.7 \\
        --target 200 --reason "next print should beat on data center"
  python3 -m journal.journal grade           # resolve any forecasts past their horizon
  python3 -m journal.journal calibration     # print calibration buckets

Calibration math: if you say "70% confident" 10 times and are right 4 times,
you are overconfident; if right 9 times, you are underconfident. The goal is
to land each bucket near its stated probability.
"""
from __future__ import annotations
import argparse, hashlib, sys
from datetime import date, datetime, timedelta
from pathlib import Path
import duckdb, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.db import kb, PRICES_DB  # noqa: E402


def add_forecast(ticker: str, direction: str, horizon: int, prob: float,
                 target: float | None, rationale: str) -> str:
    direction = direction.upper()
    assert direction in ("UP", "DOWN"), "direction must be UP or DOWN"
    assert 0 < prob < 1, "prob must be in (0,1)"
    fid = hashlib.sha256(f"{ticker}|{datetime.utcnow().isoformat()}".encode()).hexdigest()[:24]
    con = kb()
    con.execute(
        """INSERT INTO forecasts
           (forecast_id, ticker, horizon_days, direction, target_price, probability, rationale)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [fid, ticker.upper(), horizon, direction, target, prob, rationale]
    )
    con.close()
    print(f"Forecast saved: {ticker} {direction} prob={prob:.0%} horizon={horizon}d  id={fid}")
    return fid


def grade_due() -> int:
    con = kb()
    pending = con.execute(
        """SELECT forecast_id, made_at, ticker, horizon_days, direction, target_price, probability
           FROM forecasts WHERE resolved_at IS NULL"""
    ).fetch_df()
    if pending.empty:
        con.close()
        print("No pending forecasts.")
        return 0
    pc = duckdb.connect(str(PRICES_DB), read_only=True)
    resolved = 0
    for _, f in pending.iterrows():
        made = pd.to_datetime(f["made_at"]).date()
        due = made + timedelta(days=int(f["horizon_days"]))
        if due > date.today():
            continue
        p_made = pc.execute(
            "SELECT adj_close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date ASC LIMIT 1",
            [f["ticker"], made]
        ).fetchone()
        p_due = pc.execute(
            "SELECT adj_close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date ASC LIMIT 1",
            [f["ticker"], due]
        ).fetchone()
        if not p_made or not p_due:
            continue
        actual = float(p_due[0])
        moved_up = actual > float(p_made[0])
        correct = (f["direction"] == "UP" and moved_up) or (f["direction"] == "DOWN" and not moved_up)
        con.execute(
            "UPDATE forecasts SET resolved_at = now(), actual_price = ?, correct = ? WHERE forecast_id = ?",
            [actual, correct, f["forecast_id"]]
        )
        print(f"  Resolved {f['ticker']}: said {f['direction']} @ {f['probability']:.0%} → "
              f"{p_made[0]:.2f} → {actual:.2f}  ({'✓' if correct else '✗'})")
        resolved += 1
    pc.close()
    con.close()
    print(f"\nResolved {resolved} forecasts.")
    return resolved


def calibration_report() -> pd.DataFrame:
    con = kb()
    df = con.execute(
        "SELECT probability, correct FROM forecasts WHERE resolved_at IS NOT NULL"
    ).fetch_df()
    con.close()
    if df.empty:
        print("No resolved forecasts yet. Add some with `forecast`, then `grade` after their horizon.")
        return df
    buckets = [(0.5, 0.6), (0.6, 0.7), (0.7, 0.8), (0.8, 0.9), (0.9, 1.0)]
    rows = []
    for lo, hi in buckets:
        m = df[(df["probability"] >= lo) & (df["probability"] < hi)]
        if m.empty:
            rows.append({"bucket": f"{int(lo*100)}-{int(hi*100)}%", "n": 0, "hit_rate_pct": None})
            continue
        rows.append({
            "bucket": f"{int(lo*100)}-{int(hi*100)}%",
            "n": len(m),
            "hit_rate_pct": round(float(m["correct"].mean() * 100), 1),
            "stated_avg_pct": round(float(m["probability"].mean() * 100), 1),
        })
    out = pd.DataFrame(rows)
    print("\nCalibration:")
    print(out.to_string(index=False))
    return out


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forecast")
    f.add_argument("ticker")
    f.add_argument("--direction", required=True, choices=["UP", "DOWN", "up", "down"])
    f.add_argument("--horizon", type=int, required=True)
    f.add_argument("--prob", type=float, required=True)
    f.add_argument("--target", type=float, default=None)
    f.add_argument("--reason", default="")
    sub.add_parser("grade")
    sub.add_parser("calibration")
    args = ap.parse_args()

    if args.cmd == "forecast":
        add_forecast(args.ticker, args.direction, args.horizon, args.prob, args.target, args.reason)
    elif args.cmd == "grade":
        grade_due()
    elif args.cmd == "calibration":
        calibration_report()


if __name__ == "__main__":
    main()
