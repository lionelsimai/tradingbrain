#!/usr/bin/env python3
"""Sell-side scorer for current holdings.

Mirrors realtime_picks but scores EXIT urgency on positions you own
(read from config/holdings.yaml). Each position is graded across six
exit triggers and ranked by composite sell_score:

    1. STOP_HIT           — price < user stop OR cost_basis - 2*ATR
    2. TREND_BROKEN       — close < MA50 after being above it
    3. PARABOLIC_RSI      — RSI(14) > 85 (mean-reversion risk)
    4. POST_EARNINGS_GAP  — reported in last 3 trading days AND gapped >+10%
    5. RELATIVE_WEAKNESS  — 20d RS vs SPY < -5% (sector rotation away)
    6. TARGET_HIT         — price >= user target

Verdict mapping:
    sell_score >= 0.70  →  SELL          (act now)
    sell_score >= 0.45  →  TRIM          (cut 1/2 to 2/3)
    sell_score >= 0.25  →  WATCH         (tighten stop)
    else                →  HOLD

Output: reports/sell-signals-latest.json + markdown table to stdout.
"""
from __future__ import annotations
import argparse, json
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb, pandas as pd, yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
HOLDINGS = ROOT / "config" / "holdings.yaml"
PRICES = ROOT / "data" / "prices.duckdb"
EARNINGS = ROOT / "data" / "earnings_calendar.parquet"
SNAP = ROOT / "data" / "intraday_snap.parquet"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)
SGT = ZoneInfo("Asia/Singapore")
ET = ZoneInfo("America/New_York")


# ── helpers ────────────────────────────────────────────────────────────
def rsi(s: pd.Series, p: int = 14) -> float:
    if len(s) < p + 1:
        return 50.0
    d = s.diff().dropna()
    up = d.clip(lower=0).tail(p).mean()
    dn = (-d.clip(upper=0)).tail(p).mean()
    if dn == 0:
        return 100.0
    rs = up / dn
    return float(100 - 100 / (1 + rs))


def atr(df: pd.DataFrame, p: int = 14) -> float:
    if len(df) < p + 1:
        return float((df["high"] - df["low"]).tail(p).mean() or 0)
    h, l, c = df["high"], df["low"], df["close"].shift(1)
    tr = pd.concat([h - l, (h - c).abs(), (l - c).abs()], axis=1).max(axis=1)
    return float(tr.tail(p).mean())


def load_snap() -> dict[str, dict]:
    if not SNAP.exists():
        return {}
    df = pd.read_parquet(SNAP)
    return {r["ticker"]: r.to_dict() for _, r in df.iterrows()}


def load_recent_earnings(window_trading_days: int = 3) -> dict[str, str]:
    if not EARNINGS.exists():
        return {}
    df = pd.read_parquet(EARNINGS)
    today = date.today()
    cutoff_back = today - timedelta(days=window_trading_days * 2)
    cutoff_fwd = today + timedelta(days=window_trading_days * 2)
    df["report_date"] = pd.to_datetime(df["report_date"]).dt.date
    df = df[(df["report_date"] >= cutoff_back) & (df["report_date"] <= cutoff_fwd)]
    return {r["ticker"]: r["report_date"].isoformat() for _, r in df.iterrows()}


# ── scorer ─────────────────────────────────────────────────────────────
def score_exit(pos: dict, df: pd.DataFrame, spy: pd.DataFrame,
               snap: dict | None, earnings_date: str | None,
               defaults: dict) -> dict:
    last = float(snap["last_price"]) if snap and snap.get("last_price") else float(df["close"].iloc[-1])
    ma50 = float(df["close"].tail(50).mean()) if len(df) >= 50 else last
    ma200 = float(df["close"].tail(200).mean()) if len(df) >= 200 else last
    rsi14 = rsi(df["close"], 14)
    atr14 = atr(df, 14)

    ret20 = float(df["close"].pct_change(20).iloc[-1]) if len(df) > 20 else 0.0
    spy20 = float(spy["close"].pct_change(20).iloc[-1]) if len(spy) > 20 else 0.0
    rs20 = (ret20 - spy20) * 100  # in pct

    cb = float(pos["cost_basis"])
    user_stop = pos.get("stop") or (cb - defaults["stop_atr_mult"] * atr14)
    user_target = pos.get("target") or (cb + defaults["target_atr_mult"] * atr14)

    triggers = []
    score = 0.0

    # 1. STOP_HIT
    if last <= user_stop:
        triggers.append({"name": "STOP_HIT",
                         "detail": f"${last:.2f} ≤ stop ${user_stop:.2f}"})
        score += 0.50

    # 2. TREND_BROKEN
    if last < ma50 and last < ma200:
        triggers.append({"name": "TREND_BROKEN",
                         "detail": f"below MA50 (${ma50:.2f}) and MA200 (${ma200:.2f})"})
        score += 0.35
    elif last < ma50:
        triggers.append({"name": "MA50_BREAK",
                         "detail": f"closed below MA50 (${ma50:.2f})"})
        score += 0.20

    # 3. PARABOLIC_RSI
    if rsi14 > 85:
        triggers.append({"name": "PARABOLIC_RSI",
                         "detail": f"RSI {rsi14:.1f} — mean-reversion risk"})
        score += 0.30
    elif rsi14 > 75:
        triggers.append({"name": "OVERBOUGHT",
                         "detail": f"RSI {rsi14:.1f} — overbought"})
        score += 0.10

    # 4. POST_EARNINGS_GAP (gapped >+10% in last bar AND just reported)
    if earnings_date:
        if len(df) >= 2:
            gap_pct = (last / float(df["close"].iloc[-2]) - 1) * 100
            if gap_pct > 10:
                triggers.append({"name": "POST_EARNINGS_GAP",
                                 "detail": f"+{gap_pct:.1f}% post-earnings ({earnings_date}); fade risk"})
                score += 0.25

    # 5. RELATIVE_WEAKNESS
    if rs20 < -5:
        triggers.append({"name": "RELATIVE_WEAKNESS",
                         "detail": f"20d RS vs SPY {rs20:+.1f}% — rotation away"})
        score += 0.25

    # 6. TARGET_HIT
    if last >= user_target:
        triggers.append({"name": "TARGET_HIT",
                         "detail": f"${last:.2f} ≥ target ${user_target:.2f} — book profits"})
        score += 0.40

    # P&L context
    pnl_pct = (last - cb) / cb * 100
    pnl_dollars = (last - cb) * float(pos["shares"])
    days_held = (date.today() - date.fromisoformat(str(pos["opened"]))).days if pos.get("opened") else None

    verdict = "HOLD"
    if score >= 0.70:
        verdict = "SELL"
    elif score >= 0.45:
        verdict = "TRIM"
    elif score >= 0.25:
        verdict = "WATCH"

    return {
        "ticker": pos["ticker"],
        "shares": float(pos["shares"]),
        "cost_basis": cb,
        "last": round(last, 2),
        "pnl_pct": round(pnl_pct, 2),
        "pnl_dollars": round(pnl_dollars, 2),
        "days_held": days_held,
        "rsi": round(rsi14, 1),
        "ma50": round(ma50, 2),
        "ma200": round(ma200, 2),
        "rs20_vs_spy": round(rs20, 2),
        "stop": round(float(user_stop), 2),
        "target": round(float(user_target), 2),
        "sell_score": round(min(score, 1.0), 2),
        "verdict": verdict,
        "triggers": triggers,
        "thesis": pos.get("thesis", ""),
    }


# ── main ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdings", type=str, default=str(HOLDINGS))
    args = ap.parse_args()

    h = yaml.safe_load(Path(args.holdings).read_text()) or {}
    positions = h.get("positions") or []
    defaults = {**{"stop_atr_mult": 2.0, "target_atr_mult": 4.0},
                **(h.get("defaults") or {})}

    sgt = datetime.now(SGT)
    et = datetime.now(ET)

    if not positions:
        out = {
            "asof": datetime.utcnow().isoformat() + "Z",
            "asof_sgt": sgt.isoformat(),
            "asof_et": et.isoformat(),
            "positions": [],
            "note": "No positions in config/holdings.yaml — add some to enable sell scoring.",
        }
        (REPORTS / "sell-signals-latest.json").write_text(json.dumps(out, indent=2))
        print("No positions configured. Edit config/holdings.yaml and re-run.")
        return

    con = duckdb.connect(str(PRICES), read_only=True)
    spy = con.execute(
        "SELECT date, open, high, low, close, volume FROM prices "
        "WHERE ticker='SPY' ORDER BY date"
    ).fetchdf()
    snaps = load_snap()
    earnings = load_recent_earnings(3)

    rows = []
    for pos in positions:
        t = pos["ticker"]
        df = con.execute(
            "SELECT date, open, high, low, close, volume FROM prices "
            "WHERE ticker=? ORDER BY date",
            [t],
        ).fetchdf()
        if df.empty:
            rows.append({"ticker": t, "verdict": "NO_DATA",
                         "note": "ticker not in prices DB — run intraday_snap and ingest"})
            continue
        rows.append(score_exit(pos, df, spy, snaps.get(t),
                               earnings.get(t), defaults))

    rows.sort(key=lambda r: r.get("sell_score", 0), reverse=True)

    out = {
        "asof": datetime.utcnow().isoformat() + "Z",
        "asof_sgt": sgt.isoformat(),
        "asof_et": et.isoformat(),
        "positions": rows,
    }
    out_path = REPORTS / "sell-signals-latest.json"
    out_path.write_text(json.dumps(out, indent=2, default=str))

    # Pretty print
    print(f"📉 Sell signals · {sgt:%H:%M} SGT ({et:%H:%M} ET)\n")
    print(f"{'rk':>2}  {'tkr':>5}  {'sh':>5}  {'cost':>8}  {'now':>8}  "
          f"{'P&L%':>6}  {'P&L$':>9}  {'score':>5}  verdict")
    for i, r in enumerate(rows, 1):
        if r.get("verdict") == "NO_DATA":
            print(f"{i:>2}  {r['ticker']:>5}   --      --        --      --       --   --      NO_DATA")
            continue
        print(f"{i:>2}  {r['ticker']:>5}  {r['shares']:>5.0f}  "
              f"${r['cost_basis']:>7.2f}  ${r['last']:>7.2f}  "
              f"{r['pnl_pct']:>+5.1f}%  ${r['pnl_dollars']:>+8.0f}  "
              f"{r['sell_score']:>.2f}  {r['verdict']}")
        for tg in r.get("triggers", []):
            print(f"        ↳ {tg['name']}: {tg['detail']}")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
