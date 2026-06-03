#!/usr/bin/env python3
"""Real-time top-5 AI buys, every 15 minutes.

Pulls live intraday data, ranks universe, outputs 5 tickers with:
  - current price
  - suggested entry (limit or market based on setup)
  - stop level (1.5x ATR)
  - target (3x ATR)
  - one-line reason

No LLM. Pure compute. Designed for cron forwarding to Telegram.
"""
from __future__ import annotations
import json, math
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from zoneinfo import ZoneInfo
import duckdb, pandas as pd, yaml, yfinance as yf
import argparse

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
UNIV = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
TICKERS = sorted({t for cat in UNIV["universe"].values() for t in cat})
EARNINGS = ROOT / "data" / "earnings_calendar.parquet"
BASIS = ROOT / "reports" / "pattern-basis.json"
KNOWLEDGE = ROOT / "data" / "knowledge.duckdb"

# Reverse map: ticker -> (theme, subcategory)
_THEME_MAP = {
    "gpu_accelerators": "Silicon", "foundry_packaging": "Silicon",
    "memory_storage": "Silicon", "eda_design": "Silicon",
    "ai_connectivity_optics": "Silicon",
    "servers_systems": "Infrastructure", "cooling_thermal": "Infrastructure",
    "datacenter_reits": "Infrastructure", "cybersecurity_ai_ops": "Infrastructure",
    "power_generation": "Power", "grid_electrification": "Power",
    "nuclear_smr": "Power",
    "hyperscalers": "Hyperscaler", "ai_native_apps": "Apps",
    "robotics_autonomy": "Robotics", "adjacent_enterprise": "Enterprise",
}
TICKER_CAT = {t: (_THEME_MAP.get(sub, "Other"), sub)
              for sub, lst in UNIV["universe"].items() for t in lst}

OUT = ROOT / "reports" / "realtime-picks-latest.txt"


def load_blackout(window_days: int = 3) -> dict[str, str]:
    """Return {ticker: report_date} for tickers reporting within ±N trading days."""
    if not EARNINGS.exists():
        return {}
    try:
        df = pd.read_parquet(EARNINGS)
    except Exception:
        return {}
    today = date.today()
    cutoff_lo = today - timedelta(days=window_days * 2)
    cutoff_hi = today + timedelta(days=window_days * 2)
    df["d"] = pd.to_datetime(df["report_date"]).dt.date
    df = df[(df["d"] >= cutoff_lo) & (df["d"] <= cutoff_hi)]
    return {row.ticker: str(row.d) for row in df.itertuples()}


def load_pattern_basis() -> dict:
    if not BASIS.exists():
        return {}
    try:
        d = json.loads(BASIS.read_text()).get("summary", {})
    except Exception:
        return {}
    return d


def load_insider_flow(window_days: int = 90) -> dict[str, float]:
    """Net insider $ flow over the last N days: buys (code P) − sells (code S)."""
    if not KNOWLEDGE.exists():
        return {}
    try:
        from datetime import timedelta as _td
        cutoff = (date.today() - _td(days=window_days)).isoformat()
        con = duckdb.connect(str(KNOWLEDGE), read_only=True)
        rows = con.execute(
            f"""
            SELECT ticker,
                   SUM(CASE WHEN transaction_code='P' THEN total_value
                            WHEN transaction_code='S' THEN -total_value
                            ELSE 0 END) AS net_usd
            FROM insider_transactions
            WHERE transaction_date >= DATE '{cutoff}'
            GROUP BY ticker
            """
        ).fetchall()
        con.close()
        return {t: float(v or 0) for t, v in rows}
    except Exception:
        return {}


def get_intraday(tickers, period="5d", interval="15m"):
    """One yfinance call for all tickers at 15-min bars."""
    df = yf.download(
        tickers, period=period, interval=interval, group_by="ticker",
        progress=False, threads=True, auto_adjust=False,
    )
    return df


def score_ticker(t: str, df: pd.DataFrame) -> dict | None:
    """Compute composite score for one ticker from its 15-min bars."""
    try:
        sub = df[t].dropna() if isinstance(df.columns, pd.MultiIndex) else df.dropna()
    except (KeyError, TypeError):
        return None
    if len(sub) < 60:  # need ~15 hours of data
        return None
    closes = sub["Close"].values
    highs = sub["High"].values
    lows = sub["Low"].values
    vols = sub["Volume"].values
    last = float(closes[-1])
    if last <= 0 or not math.isfinite(last):
        return None

    # ATR over last 20 bars (~5 hours)
    tr = pd.Series(highs[-21:] - lows[-21:])
    atr = float(tr.tail(20).mean())

    # momentum scores
    ret_1h = (closes[-1] / closes[-5] - 1) if len(closes) >= 5 else 0     # ~1h
    ret_1d = (closes[-1] / closes[-26] - 1) if len(closes) >= 26 else 0   # ~1 day
    ret_5d = (closes[-1] / closes[-130] - 1) if len(closes) >= 130 else 0 # ~5 days

    # vol burst: last bar vs 20-bar avg
    vol_burst = float(vols[-1]) / max(1.0, pd.Series(vols[-21:-1]).mean())

    # RSI(14) on closes
    delta = pd.Series(closes).diff()
    up = delta.clip(lower=0).rolling(14).mean()
    dn = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = float(100 - 100 / (1 + (up.iloc[-1] / max(dn.iloc[-1], 1e-9))))

    # close vs 50-bar MA
    ma50 = float(pd.Series(closes).tail(50).mean()) if len(closes) >= 50 else last
    above_ma50 = last > ma50

    # Composite: weighted blend
    score = (
        0.30 * ret_5d +      # 5-day trend
        0.25 * ret_1d +      # 1-day momentum
        0.15 * ret_1h +      # intraday momentum
        0.15 * (1.0 if above_ma50 else -0.3) +
        0.10 * min(1.0, (vol_burst - 1.0) / 2.0) +  # volume confirmation
        0.05 * ((rsi - 50) / 50)
    )

    # Setup type
    if rsi < 35 and above_ma50 and ret_5d > 0:
        setup = "PULLBACK"
        entry = last  # buy now at market
        reason = f"RSI {rsi:.0f}, oversold in uptrend"
    elif vol_burst > 1.5 and ret_1h > 0.005:
        setup = "BREAKOUT"
        entry = last + atr * 0.25
        reason = f"vol {vol_burst:.1f}x, intraday +{ret_1h*100:.1f}%"
    elif ret_5d > 0.05 and above_ma50:
        setup = "MOMO"
        entry = last
        reason = f"5d +{ret_5d*100:.1f}%, above MA50"
    elif above_ma50:
        setup = "TREND"
        entry = last
        reason = "trend intact, above MA50"
    else:
        return None  # no setup

    stop = entry - atr * 1.5
    target = entry + atr * 3.0
    r_mult = (target - entry) / max(0.01, entry - stop)

    return dict(
        ticker=t, last=last, entry=entry, stop=stop, target=target, atr=atr,
        score=score, setup=setup, reason=reason, ret_1h=ret_1h, ret_1d=ret_1d,
        ret_5d=ret_5d, vol_burst=vol_burst, rsi=rsi, r_mult=r_mult,
    )


def regime_line() -> str:
    p = ROOT / "reports" / "hmm-regime.json"
    if not p.exists():
        return ""
    h = json.loads(p.read_text())
    return f"Regime: {h.get('acted_label','?')} (exp {int(h.get('target_exposure',0)*100)}%)"


def market_session_now() -> str:
    """ET-aware US market session label."""
    now_et = datetime.now(timezone.utc).astimezone(ZoneInfo("America/New_York"))
    h, mi, wd = now_et.hour, now_et.minute, now_et.weekday()
    if wd >= 5:
        return "CLOSED (weekend)"
    t = h * 60 + mi
    if t < 4 * 60:                    return "CLOSED"
    if t < 9 * 60 + 30:              return "PRE-MARKET"
    if t < 16 * 60:                  return "OPEN"
    if t < 20 * 60:                  return "AFTER-HOURS"
    return "CLOSED"


def verdict(rank: int, score: float, r_mult: float, setup: str, regime: str, target_exposure: float) -> str:
    if r_mult < 2 or regime in ("Crash", "Bear"):
        return "NO TRADE"
    if rank == 1 and score > 0.65 and r_mult >= 2:
        return "STRONG BUY"
    if rank <= 3 and score > 0.50 and r_mult >= 2:
        return "BUY"
    if rank <= 10 and r_mult >= 2:
        return "WATCHLIST"
    return "NO TRADE"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--max-per-theme", type=int, default=2,
                    help="Theme diversification cap; 0 disables")
    ap.add_argument("--min-buys", type=int, default=10,
                    help="Fallback fill target (top-by-score trend-intact names).")
    a = ap.parse_args()
    TOP = a.top
    MIN_BUYS = a.min_buys

    sgt = datetime.now(ZoneInfo("Asia/Singapore"))
    et = datetime.now(ZoneInfo("America/New_York"))
    session = market_session_now()

    blackout = load_blackout(3)
    pattern_basis = load_pattern_basis()
    insider_flow = load_insider_flow(90)
    print(f"# pattern-basis: {len(pattern_basis)} setups | insider: {len(insider_flow)} tickers covered")
    df_all = get_intraday(TICKERS, period="5d", interval="15m")
    picks = []
    for t in TICKERS:
        if t in blackout:
            continue
        p = score_ticker(t, df_all)
        if not p:
            continue
        # Insider tilt: nudge composite up/down by ±0.05 based on 90d net $
        net = insider_flow.get(t, 0.0)
        if net > 1_000_000:
            p["score"] += 0.05
            p["insider_signal"] = f"net +${net/1e6:.1f}M (90d)"
        elif net < -5_000_000:
            p["score"] -= 0.05
            p["insider_signal"] = f"net -${abs(net)/1e6:.1f}M (90d)"
        else:
            p["insider_signal"] = None
        # Pattern win-rate annotation — map TREND → TREND_LEADER (same family)
        setup_key = p["setup"]
        basis = pattern_basis.get(setup_key) or pattern_basis.get(
            {"TREND": "TREND_LEADER", "MOMO": "TREND_LEADER"}.get(setup_key, ""), {}
        )
        if basis:
            p["winrate_10d"] = round(basis.get("winrate_10d", 0), 1)
            p["median_10d_pct"] = round(basis.get("median_10d", 0), 2)
            p["basis_n"] = basis.get("n_10d", 0)
        picks.append(p)
    picks.sort(key=lambda x: x["score"], reverse=True)

    # Theme diversification: cap N per theme before verdict
    if a.max_per_theme and a.max_per_theme > 0:
        seen_theme = {}
        diversified = []
        leftovers = []
        for p in picks:
            theme = TICKER_CAT.get(p["ticker"], ("Other", "uncategorized"))[0]
            if seen_theme.get(theme, 0) < a.max_per_theme:
                seen_theme[theme] = seen_theme.get(theme, 0) + 1
                diversified.append(p)
            else:
                leftovers.append(p)
        picks = diversified + leftovers

    # Annotate every pick with a verdict so we can filter
    for i, p in enumerate(picks, 1):
        p["verdict"] = verdict(
            rank=i, score=p["score"], r_mult=p["r_mult"],
            setup=p["setup"], regime=session, target_exposure=0.0,
        )

    buys = [p for p in picks if p["verdict"] in ("STRONG BUY", "BUY")]

    # Fallback so we always have ≥5 buys: take top-by-score trend-intact names
    if len(buys) < MIN_BUYS:
        existing = {p["ticker"] for p in buys}
        for p in picks:
            if len(buys) >= MIN_BUYS:
                break
            if p["ticker"] in existing:
                continue
            if p.get("score", 0) > 0 and p.get("setup") in ("TREND", "MOMO", "BREAKOUT", "PULLBACK"):
                p["verdict"] = "BUY"
                buys.append(p)
                existing.add(p["ticker"])

    top = buys[:TOP]
    for p in top:
        p["action"] = "Buy"
        theme, sub = TICKER_CAT.get(p["ticker"], ("Other", "uncategorized"))
        p["theme"] = theme
        p["subcategory"] = sub

    lines = [
        f"🧠 Top {len(top)} AI buys · {sgt:%H:%M} SGT ({et:%H:%M} ET · {session})",
    ]
    if rl := regime_line():
        lines.append(rl)
    lines.append("")
    if not top:
        lines.append("No clean setups right now.")
    else:
        theme_order = ["Silicon", "Infrastructure", "Power",
                       "Hyperscaler", "Apps", "Robotics", "Enterprise", "Other"]
        grouped = {th: [p for p in top if p.get("theme") == th] for th in theme_order}
        rank = 0
        for th in theme_order:
            group = grouped.get(th) or []
            if not group:
                continue
            lines.append(f"── {th} ──")
            for p in group:
                rank += 1
                extras = []
                if p.get("winrate_10d"):
                    extras.append(f"win {p['winrate_10d']}% (10d, n={p.get('basis_n', 0)})")
                if p.get("insider_signal"):
                    extras.append(f"👁 {p['insider_signal']}")
                extras_str = ("  ·  " + "  ·  ".join(extras)) if extras else ""
                lines.append(
                    f"{rank:>2}. {p['ticker']:>5}  ${p['last']:>7.2f}  "
                    f"entry ${p['entry']:>7.2f}  stop ${p['stop']:>6.2f}  "
                    f"tgt ${p['target']:>7.2f}  R{p['r_mult']:.1f}  "
                    f"{p['subcategory']}  ·  {p['setup']} · {p['verdict']}{extras_str}"
                )
                lines.append(f"    {p['setup']}: {p['reason']}")
            lines.append("")
    lines.append("🔗 https://lionelsim.zo.space/trading")

    msg = "\n".join(lines)
    OUT.write_text(msg)
    hmm_path = ROOT / "reports" / "hmm-regime.json"
    hmm = json.loads(hmm_path.read_text()) if hmm_path.exists() else {}
    out_json = ROOT / "reports" / "realtime-picks-latest.json"
    out_json.write_text(json.dumps({
        "asof": sgt.isoformat(),
        "asof_sgt": sgt.strftime("%H:%M"),
        "asof_et": et.strftime("%H:%M"),
        "market_status": session,
        "regime": hmm.get("acted_label", "Unknown"),
        "target_exposure": hmm.get("target_exposure", 0.0),
        "picks": top,
    }, indent=2, default=str))
    print(msg)


if __name__ == "__main__":
    main()
