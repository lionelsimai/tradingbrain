#!/usr/bin/env python3
"""Hourly market pulse — compact Telegram-ready snapshot.

Designed for cost-efficiency: the script does all the work (price reads,
formatting), so the cron agent just runs it and forwards stdout to Telegram.

Outputs a ~10-line message:
  - regime + SPY/VIX
  - top 3 BUYs from latest.json
  - intraday movers in our universe (>=2% over the last hour, yfinance 5m bars)
  - any new high-signal events (insider Buy, fresh 8-K, etc.) in last 2h
  - link to the dashboard
"""
from __future__ import annotations
import json, sys, subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.db import kb  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
LATEST = ROOT / "reports" / "latest.json"
PULSE = ROOT / "reports" / "pulse-latest.txt"

SGT = timezone(timedelta(hours=8))
NYT_OFFSET = -4  # EDT in May; brain only uses for display


def load_latest() -> dict:
    if not LATEST.exists():
        return {}
    try:
        return json.loads(LATEST.read_text())
    except Exception:
        return {}


def universe_tickers() -> list[str]:
    uni = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    out: list[str] = []
    for cat, tks in uni.get("universe", {}).items():
        out.extend(tks)
    return sorted(set(out))


def intraday_movers(tickers: list[str], lookback_min: int = 60) -> list[tuple[str, float, float]]:
    """Returns list of (ticker, pct_change_1h, last_price), sorted by |pct| desc."""
    try:
        import yfinance as yf
    except Exception:
        return []
    if not tickers:
        return []
    # yfinance batch download, 5-min bars, 1d period
    df = yf.download(
        tickers, period="1d", interval="5m",
        progress=False, auto_adjust=False, group_by="ticker", threads=True,
    )
    if df is None or df.empty:
        return []
    bars_needed = max(2, lookback_min // 5)
    out = []
    for t in tickers:
        try:
            sub = df[t]["Close"].dropna() if t in df.columns.get_level_values(0) else df["Close"].dropna()
        except Exception:
            continue
        if len(sub) < bars_needed:
            continue
        last = float(sub.iloc[-1])
        prior = float(sub.iloc[-bars_needed])
        if prior <= 0:
            continue
        pct = (last / prior - 1) * 100
        out.append((t, pct, last))
    out.sort(key=lambda r: abs(r[1]), reverse=True)
    return out


def recent_events(hours: int = 2) -> list[str]:
    """Pull insider buys + fresh 8-Ks + breaking news from last N hours."""
    con = kb()
    out: list[str] = []
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Insider buys in last N hours
    try:
        rows = con.execute(
            """SELECT ticker, insider_name, shares, total_value
               FROM insider_transactions
               WHERE transaction_code = 'P' AND ingested_at >= ?
               ORDER BY total_value DESC LIMIT 5""",
            [since],
        ).fetchall()
        for r in rows:
            tkr, name, sh, val = r
            val_str = f"${val/1e6:.1f}M" if val and val >= 1e6 else (f"${val/1e3:.0f}K" if val else "?")
            out.append(f"💰 {tkr} insider BUY: {name[:24]} {val_str}")
    except Exception:
        pass
    # Fresh 8-K filings
    try:
        rows = con.execute(
            """SELECT ticker, title FROM documents
               WHERE source = 'edgar:8-K' AND ingested_at >= ?
               ORDER BY ingested_at DESC LIMIT 3""",
            [since],
        ).fetchall()
        for tkr, title in rows:
            out.append(f"📄 {tkr} 8-K: {(title or '')[:60]}")
    except Exception:
        pass
    # Recent news headlines tagged with universe tickers
    try:
        rows = con.execute(
            """SELECT ticker, title FROM documents
               WHERE source LIKE 'rss:%' AND ticker IS NOT NULL AND ingested_at >= ?
               ORDER BY ingested_at DESC LIMIT 3""",
            [since],
        ).fetchall()
        for tkr, title in rows:
            out.append(f"📰 {tkr}: {(title or '')[:60]}")
    except Exception:
        pass
    return out[:6]


def format_pulse() -> str:
    data = load_latest()
    now_sgt = datetime.now(SGT)
    et_hour = (now_sgt.hour - 12) % 24
    et_label = f"{et_hour:02d}:{now_sgt.minute:02d} ET"
    sgt_label = now_sgt.strftime("%H:%M SGT")

    lines: list[str] = [f"🧠 TradingBrain pulse · {sgt_label} ({et_label})"]

    if data:
        regime = data.get("regime_label", "?")
        rscore = data.get("regime_score", 0)
        spy = data.get("spy_close")
        vix = data.get("vix_close")
        macro = f"Regime: {regime} {rscore:.2f}"
        if spy:
            macro += f" · SPY {spy:.2f}"
        if vix:
            macro += f" · VIX {vix:.1f}"
        lines.append(macro)
        buys = [w for w in data.get("watchlist", []) if w.get("action") == "BUY"][:3]
        if buys:
            buy_str = " · ".join(f"{b['ticker']} {b['confidence']:.2f}" for b in buys)
            lines.append(f"🟢 BUY top-3: {buy_str}")
    else:
        lines.append("Regime: (no digest yet — daily run pending)")

    # Intraday movers — focus on watchlist + a few flagged sectors
    watch = [w["ticker"] for w in data.get("watchlist", [])] if data else []
    focus = watch[:25] if watch else universe_tickers()[:25]
    movers = intraday_movers(focus, lookback_min=60)
    sig_movers = [m for m in movers if abs(m[1]) >= 1.5][:4]
    if sig_movers:
        mv_str = " · ".join(f"{t} {p:+.1f}%" for t, p, _ in sig_movers)
        lines.append(f"⚡ 1h movers: {mv_str}")

    events = recent_events(hours=2)
    for ev in events[:4]:
        lines.append(ev)

    lines.append("🔗 https://lionelsim.zo.space/trading")
    return "\n".join(lines)


def run_step(cmd: list[str], timeout: int = 60) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.returncode, (r.stdout + r.stderr)[-2000:]
    except Exception as e:
        return -1, f"step failed: {e}"


def main():
    # Hourly live ingest — scrape the web, then embed any new docs.
    print("scraping web sources…", file=sys.stderr)
    rc, out = run_step([sys.executable, "-m", "scripts.ingest.web_scrape"], timeout=90)
    last_line = (out.strip().splitlines() or ["?"])[-1]
    print(f"  scrape: {last_line}", file=sys.stderr)
    rc, out = run_step([sys.executable, "scripts/embed.py"], timeout=120)
    last_line = (out.strip().splitlines() or ["?"])[-1]
    print(f"  embed:  {last_line}", file=sys.stderr)

    msg = format_pulse()
    PULSE.write_text(msg)
    print(msg)


if __name__ == "__main__":
    main()
