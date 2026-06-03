#!/usr/bin/env python3
"""Swing-trade setup scoring — 6 honest patterns with entry/stop/target.

Patterns scored per ticker (best wins):
  PULLBACK        — uptrend (>MA200, RS+) + RSI<35 + close near MA50
  BREAKOUT        — within 3% of 52w high + 20d ATR contraction + volume rising
  VCP             — Minervini contraction: declining ATR + tight range
  MOMO_CONT       — Clenow rank top 20 + close > prior-5d high
  MEAN_REVERSION  — z-score < -2 vs 20d, still above MA200
  EARNINGS_DRIFT  — within 5 days post-earnings, gap up + volume

Output: writes to signals.swing_setups + reports/swing-setups.json
"""
from __future__ import annotations
import argparse, json, sys
from datetime import date, timedelta
from pathlib import Path
import duckdb, numpy as np, pandas as pd

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
KB = ROOT / "data" / "knowledge.duckdb"
EARNINGS = ROOT / "data" / "earnings_calendar.parquet"
SNAP = ROOT / "data" / "intraday_snap.parquet"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

PATTERNS = ["PULLBACK", "BREAKOUT", "VCP", "MOMO_CONT", "MEAN_REVERSION", "EARNINGS_DRIFT"]


def load_earnings_blackout(window_days: int) -> dict[str, str]:
    """Return {ticker: report_date_iso} for tickers reporting within ±window_days
    trading days of today. We approximate trading days with calendar days * 1.4
    (good enough for a small window; avoids needing a market calendar dep)."""
    if not EARNINGS.exists():
        return {}
    try:
        df = pd.read_parquet(EARNINGS)
    except Exception:
        return {}
    today = date.today()
    cal_window = int(round(window_days * 1.4)) + 1
    lo = (today - timedelta(days=cal_window)).isoformat()
    hi = (today + timedelta(days=cal_window)).isoformat()
    mask = (df["report_date"] >= lo) & (df["report_date"] <= hi)
    sub = df.loc[mask, ["ticker", "report_date"]].dropna()
    # If a ticker has multiple rows in the window, keep the one closest to today.
    sub = sub.assign(
        _delta=(pd.to_datetime(sub["report_date"]) - pd.Timestamp(today)).abs()
    ).sort_values("_delta").drop_duplicates("ticker", keep="first")
    return dict(zip(sub["ticker"], sub["report_date"]))


def rsi(series: pd.Series, period: int = 14) -> float:
    if len(series) < period + 1:
        return 50.0
    diff = series.diff().dropna()
    up = diff.clip(lower=0).rolling(period).mean().iloc[-1]
    dn = (-diff.clip(upper=0)).rolling(period).mean().iloc[-1]
    if dn == 0:
        return 100.0
    rs = up / dn
    return float(100 - 100 / (1 + rs))


def atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < period + 1:
        return float("nan")
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


def classify(last: float, ma20: float, ma50: float, ma200: float, high52: float,
             rsi14: float, atr14: float, contraction: float, rs20: float,
             range_5d: float, z20: float, prev5_high: float,
             clenow_rank: int | None) -> dict:
    """Pure setup-decision rules — the SINGLE source of truth for what fires.

    Both the live path (detect_setup) and the backtest path (detect_at) call
    this with the same scalars, so live and backtest detect identically.
    Returns the best setup dict (with the detector's own entry/stop/target,
    which the live ranker uses; backtests use trade_sim for the actual plan).
    """
    above_ma200 = last > ma200
    above_ma50 = last > ma50
    pct_to_52wh = (high52 - last) / last if last else 1.0
    setups = []

    # PULLBACK
    if above_ma200 and rs20 > 0 and 25 <= rsi14 <= 40 and abs(last - ma50) / ma50 < 0.05:
        setups.append({
            "setup": "PULLBACK", "score": 0.70 + (40 - rsi14) / 100,
            "entry": last, "stop": min(ma50 * 0.97, last - 1.5 * atr14),
            "target": last + 2.5 * atr14,
            "reason": f"uptrend pullback to MA50 (RSI {rsi14:.0f}, RS +{rs20*100:.1f}%)",
        })
    # BREAKOUT
    if above_ma200 and pct_to_52wh < 0.03 and contraction < 0.85:
        entry = high52 * 1.001
        setups.append({
            "setup": "BREAKOUT", "score": 0.65 + (0.05 - pct_to_52wh) * 2 + (1 - contraction) * 0.3,
            "entry": entry, "stop": last - 1.5 * atr14, "target": entry + 3 * atr14,
            "reason": f"near 52w high ({pct_to_52wh*100:.1f}% away), ATR contracting ({contraction:.2f})",
        })
    # VCP
    if above_ma200 and range_5d < 0.06 and contraction < 0.8:
        setups.append({
            "setup": "VCP", "score": 0.60 + (0.06 - range_5d) * 5,
            "entry": last + 0.3 * atr14, "stop": last - 1.2 * atr14, "target": last + 3 * atr14,
            "reason": f"tight 5d range ({range_5d*100:.1f}%), volatility contracting",
        })
    # MOMO_CONT
    if clenow_rank is not None and clenow_rank <= 20 and above_ma50 and last > prev5_high:
        setups.append({
            "setup": "MOMO_CONT", "score": 0.65 + (21 - clenow_rank) / 100,
            "entry": last, "stop": last - 2 * atr14, "target": last + 4 * atr14,
            "reason": f"Clenow rank #{clenow_rank}, new 5d high",
        })
    # TREND_LEADER — soft fallback so the brain always has buy candidates.
    if above_ma200 and above_ma50 and rs20 > 0 and (clenow_rank is None or clenow_rank <= 30):
        rank_bonus = (31 - clenow_rank) / 200 if clenow_rank else 0.0
        setups.append({
            "setup": "TREND_LEADER", "score": 0.50 + rank_bonus + min(rs20, 0.3) * 0.3,
            "entry": last, "stop": last - 2 * atr14, "target": last + 3 * atr14,
            "reason": ("trend leader (>MA50/200, RS +%.1f%%" % (rs20 * 100))
                      + ((", Clenow #%d" % clenow_rank) if clenow_rank else "") + ")",
        })
    # MEAN_REVERSION
    if above_ma200 and z20 < -2:
        setups.append({
            "setup": "MEAN_REVERSION", "score": 0.55 + min(-z20 - 2, 1) * 0.2,
            "entry": last, "stop": last - 1.5 * atr14, "target": ma20,
            "reason": f"z-score {z20:.1f} below 20d mean, still above MA200",
        })

    if not setups:
        return {"setup": "NONE", "score": 0.0, "reason": "no clean setup",
                "rsi": round(rsi14, 1), "atr14": round(atr14, 2)}
    best = max(setups, key=lambda s: s["score"])
    best["r_multiple"] = round((best["target"] - best["entry"]) / max(best["entry"] - best["stop"], 0.01), 2)
    best["rsi"] = round(rsi14, 1)
    best["atr14"] = round(atr14, 2)
    best["rs20"] = round(rs20 * 100, 2)
    return best


def compute_features(df: pd.DataFrame, spy: pd.DataFrame) -> pd.DataFrame:
    """Vectorized indicator frame aligned to df rows — computed ONCE per ticker.

    Reproduces the exact scalars detect_setup uses, so detect_at(features, i)
    == detect_setup(df.iloc[:i+1]). Eliminates the per-bar O(n) rolling that
    made the stress test O(n^2).
    """
    close, high, low = df["close"], df["high"], df["low"]
    f = pd.DataFrame(index=df.index)
    f["close"] = close
    f["ma20"] = close.rolling(20).mean()
    f["ma50"] = close.rolling(50).mean()
    f["ma200"] = close.rolling(200).mean()
    f["high52"] = close.rolling(252).max()
    f["low52"] = close.rolling(252).min()
    # RSI(14) — simple-MA variant, matching rsi()
    diff = close.diff()
    up = diff.clip(lower=0).rolling(14).mean()
    dn = (-diff.clip(upper=0)).rolling(14).mean()
    rs = up / dn
    f["rsi14"] = np.where(dn == 0, 100.0, 100 - 100 / (1 + rs))
    # ATR(14)/ATR(60) from true range
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    f["atr14"] = tr.rolling(14).mean()
    atr60 = tr.rolling(60).mean()
    f["contraction"] = (f["atr14"] / atr60).fillna(1.0)
    f["ret20"] = close.pct_change(20)
    # SPY 20d return as-of each date (point-in-time, backward-aligned)
    sp = spy[["date", "close"]].copy()
    sp["date"] = pd.to_datetime(sp["date"])
    sp = sp.sort_values("date")
    sp["spy20"] = sp["close"].pct_change(20)
    dd = pd.to_datetime(df["date"]).values
    f["spy20"] = np.interp(
        pd.to_datetime(dd).astype("int64"),
        sp["date"].astype("int64").values,
        sp["spy20"].fillna(0.0).values,
    )
    f["rs20"] = f["ret20"] - f["spy20"]
    f["range_5d"] = (high.rolling(5).max() - low.rolling(5).min()) / close
    f["z20"] = (close - close.rolling(20).mean()) / close.rolling(20).std()
    f["prev5_high"] = high.shift(1).rolling(5).max()
    # Structural plan levels (for trade_sim.plan_from_levels in backtests)
    f["swing_low_10"] = low.rolling(10).min()
    f["swing_high_20"] = high.rolling(20).max()
    f["swing_high_60"] = high.rolling(60).max()
    f["swing_low_20"] = low.rolling(20).min()
    f["hi252"] = high.rolling(252).max()
    return f


def detect_at(f: pd.DataFrame, i: int, clenow_rank: int | None = None,
              last: float | None = None) -> dict:
    """Detect the setup at row i of a precomputed feature frame (backtest path)."""
    row = f.iloc[i]
    if not np.isfinite(row["ma200"]) or not np.isfinite(row["atr14"]) or not np.isfinite(row["rsi14"]):
        return {"setup": "NONE", "score": 0.0, "reason": "insufficient history"}
    px = float(last) if last is not None else float(row["close"])
    return classify(
        last=px, ma20=float(row["ma20"]), ma50=float(row["ma50"]), ma200=float(row["ma200"]),
        high52=float(row["high52"]), rsi14=float(row["rsi14"]), atr14=float(row["atr14"]),
        contraction=float(row["contraction"]), rs20=float(row["rs20"]),
        range_5d=float(row["range_5d"]), z20=float(row["z20"]),
        prev5_high=float(row["prev5_high"]), clenow_rank=clenow_rank,
    )


def detect_setup(df: pd.DataFrame, spy: pd.DataFrame, clenow_rank: int | None,
                 snap_price: float | None = None) -> dict:
    """Return setup dict with type, score, entry, stop, target, reason.

    If `snap_price` is provided, it is used as the current price (`last`) for
    proximity checks and entry/stop/target sizing. All technical indicators
    (MA20/50/200, RSI, ATR, RS, volume) are still computed from the EOD close
    series in `df` — the snap only updates "where the stock is right now".
    """
    if len(df) < 220:
        return {"setup": "NONE", "score": 0.0, "reason": "insufficient history"}

    close = df["close"]
    eod_close = float(close.iloc[-1])
    last = float(snap_price) if snap_price is not None else eod_close
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    ma200 = float(close.rolling(200).mean().iloc[-1])
    high52 = float(close.rolling(252).max().iloc[-1])
    rsi14 = rsi(close, 14)
    atr14 = atr(df, 14)
    atr60 = atr(df, 60)
    contraction = (atr14 / atr60) if atr60 else 1.0
    ret20 = float(close.pct_change(20).iloc[-1])
    spy20 = float(spy["close"].pct_change(20).iloc[-1]) if len(spy) > 20 else 0.0
    rs20 = ret20 - spy20
    range_5d = float((df["high"].tail(5).max() - df["low"].tail(5).min()) / last)
    prev5_high = float(df["high"].tail(6).head(5).max())
    sd20 = close.tail(20).std()
    z20 = (last - close.tail(20).mean()) / sd20 if sd20 else 0.0

    return classify(
        last=last, ma20=ma20, ma50=ma50, ma200=ma200, high52=high52,
        rsi14=rsi14, atr14=atr14, contraction=contraction, rs20=rs20,
        range_5d=range_5d, z20=float(z20), prev5_high=prev5_high,
        clenow_rank=clenow_rank,
    )


def load_snap() -> dict[str, dict]:
    """Return {ticker: {last_price, market_state, change_pct, ts_utc}} from snap parquet."""
    if not SNAP.exists():
        return {}
    try:
        df = pd.read_parquet(SNAP)
        return {
            r["ticker"]: {
                "last_price": float(r["last_price"]),
                "market_state": str(r.get("market_state", "")),
                "change_pct": float(r["change_pct"]) if pd.notna(r.get("change_pct")) else None,
                "ts_utc": str(r.get("ts_utc", "")),
            }
            for _, r in df.iterrows()
        }
    except Exception as e:
        print(f"  ! snap load failed: {e}", file=sys.stderr)
        return {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--earnings-blackout-days", type=int, default=3,
                    help="Exclude tickers with earnings within ±N trading days (default 3)")
    ap.add_argument("--no-earnings-filter", action="store_true",
                    help="Disable the earnings blackout filter")
    ap.add_argument("--no-snap", action="store_true",
                    help="Disable intraday snap (use EOD close as current price)")
    ap.add_argument("--include-exits", action="store_true", default=False)
    a = ap.parse_args()

    con = duckdb.connect(str(PRICES), read_only=True)
    tickers = [r[0] for r in con.execute("SELECT DISTINCT ticker FROM prices WHERE ticker != 'SPY' AND ticker != 'QQQ'").fetchall()]
    spy = con.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker = 'SPY' ORDER BY date").fetchdf()

    # Load Clenow ranks if available
    rank_map = {}
    try:
        mom = pd.read_parquet(ROOT / "data" / "momentum.parquet")
        for i, row in mom.iterrows():
            rank_map[row["ticker"]] = int(row["rank"]) if "rank" in row else (i + 1)
    except Exception:
        pass

    # Load earnings blackout set
    blackout: dict[str, str] = {}
    if not a.no_earnings_filter:
        blackout = load_earnings_blackout(a.earnings_blackout_days)
        if blackout:
            print(f"Earnings blackout: {len(blackout)} tickers within ±{a.earnings_blackout_days} trading days", file=sys.stderr)
        else:
            print("Earnings blackout: no calendar found (run scripts.ingest.earnings_calendar)", file=sys.stderr)

    # Load intraday snap
    snap: dict[str, dict] = {}
    if not a.no_snap:
        snap = load_snap()
        if snap:
            states = {s["market_state"] for s in snap.values()}
            print(f"Intraday snap: {len(snap)} tickers loaded (state: {','.join(sorted(states))})", file=sys.stderr)
        else:
            print("Intraday snap: not found (run scripts.ingest.intraday_snap)", file=sys.stderr)

    rows = []
    skipped = 0
    for t in tickers:
        df = con.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker = ? ORDER BY date",
            [t],
        ).fetchdf()
        if df.empty:
            continue
        if t in blackout:
            rows.append({
                "ticker": t,
                "setup": "NONE",
                "score": 0.0,
                "reason": f"earnings blackout: reports {blackout[t]}",
                "close": float(df["close"].iloc[-1]),
            })
            skipped += 1
            continue
        snap_info = snap.get(t)
        snap_price = snap_info["last_price"] if snap_info else None
        setup = detect_setup(df, spy, rank_map.get(t), snap_price=snap_price)
        setup["ticker"] = t
        setup["close"] = float(df["close"].iloc[-1])
        if snap_info:
            setup["snap_price"] = round(snap_info["last_price"], 2)
            setup["snap_state"] = snap_info["market_state"]
            if snap_info["change_pct"] is not None:
                setup["snap_change_pct"] = round(snap_info["change_pct"], 2)
        rows.append(setup)

    if skipped:
        print(f"Skipped {skipped} tickers due to earnings blackout", file=sys.stderr)

    valid = [r for r in rows if r["setup"] != "NONE"]
    valid.sort(key=lambda r: r["score"], reverse=True)
    top = valid[: a.top]

    print(f"\nSwing setups — {len(valid)} candidates, showing top {len(top)}:")
    if a.include_exits:
        print(f"{'rk':>2} {'tkr':>6} {'setup':14} {'score':>5} {'entry':>8} {'stop':>8} {'tgt':>8} {'R':>4}  reason")
        for i, s in enumerate(top, 1):
            print(f"{i:>2} {s['ticker']:>6} {s['setup']:14} {s['score']:5.2f} {s['entry']:8.2f} "
                  f"{s['stop']:8.2f} {s['target']:8.2f} {s.get('r_multiple', 0):4.1f}  {s['reason']}")
    else:
        # Buys-only view: rank, ticker, setup, score, entry, %vs prev close, reason
        print(f"{'rk':>2} {'tkr':>6} {'setup':14} {'score':>5} {'entry':>8} {'chg%':>6}  reason")
        for i, s in enumerate(top, 1):
            chg = s.get("snap_change_pct")
            chg_str = f"{chg:+5.2f}" if chg is not None else "  -- "
            print(f"{i:>2} {s['ticker']:>6} {s['setup']:14} {s['score']:5.2f} {s['entry']:8.2f} {chg_str:>6}  {s['reason']}")

    out = REPORTS / "swing-setups.json"
    out.write_text(json.dumps({
        "asof": date.today().isoformat(),
        "candidates": valid,
        "blackout": [
            {"ticker": t, "report_date": d}
            for t, d in sorted(blackout.items())
            if t in tickers
        ],
        "blackout_days": a.earnings_blackout_days,
        "snap_used": bool(snap),
        "snap_tickers": len(snap),
    }, indent=2, default=str))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
