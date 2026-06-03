#!/usr/bin/env python3
"""Pre-market briefing — runs 1 hour before US open (20:30 SGT during DST).

Steps:
  1. Refresh prices (yfinance close-to-now)
  2. Run scrape + embed + swing_setup + brain
  3. Pull pre-market quotes for top setups
  4. Compose a long-form briefing: overnight macro, swing setups w/ base rates,
     earnings calendar, insider buys overnight
  5. Save reports/premarket-<date>.md + reports/premarket-latest.md
"""
from __future__ import annotations
import json, subprocess, sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import yfinance as yf, duckdb, yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
KB = ROOT / "data" / "knowledge.duckdb"
REPORTS = ROOT / "reports"
SGT = ZoneInfo("Asia/Singapore")
ET = ZoneInfo("America/New_York")
PY = sys.executable


def run(cmd: list[str], timeout: int = 180) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def premarket_quotes(tickers: list[str]) -> dict[str, dict]:
    """Pre-market quote per ticker. Uses yfinance fast_info."""
    out = {}
    for t in tickers:
        try:
            tk = yf.Ticker(t)
            fi = tk.fast_info
            last = fi.last_price
            prev = fi.previous_close
            if last and prev:
                out[t] = {
                    "last": float(last),
                    "prev_close": float(prev),
                    "pct": (float(last) / float(prev) - 1) * 100,
                }
        except Exception:
            pass
    return out


def overnight_macro() -> dict:
    """Asia close, EU open, US futures (ES, NQ), VIX."""
    out = {}
    for label, sym in [("ES", "ES=F"), ("NQ", "NQ=F"), ("VIX", "^VIX"), ("DXY", "DX-Y.NYB"),
                        ("10Y", "^TNX"), ("Brent", "BZ=F"), ("Nikkei", "^N225"), ("HangSeng", "^HSI"),
                        ("DAX", "^GDAXI")]:
        try:
            tk = yf.Ticker(sym)
            fi = tk.fast_info
            last = float(fi.last_price)
            prev = float(fi.previous_close)
            out[label] = {"last": last, "pct": (last / prev - 1) * 100}
        except Exception:
            continue
    return out


def recent_insider_buys(hours: int = 24) -> list[dict]:
    con = duckdb.connect(str(KB), read_only=True)
    cutoff = (date.today() - timedelta(days=max(1, hours // 24))).isoformat()
    rows = con.execute(
        """SELECT ticker, insider_name, transaction_code, shares, total_value, transaction_date
           FROM insider_transactions
           WHERE transaction_code = 'P' AND filed_date >= ? AND total_value > 50000
           ORDER BY total_value DESC LIMIT 10""",
        [cutoff],
    ).fetchall()
    return [{"ticker": r[0], "name": r[1], "shares": r[3], "value": r[4], "date": r[5]} for r in rows]


def recent_8ks(hours: int = 24) -> list[dict]:
    con = duckdb.connect(str(KB), read_only=True)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    universe = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    tickers = [t for cat, lst in universe.get("categories", {}).items() for t in lst]
    if not tickers:
        return []
    placeholders = ",".join(["?"] * len(tickers))
    rows = con.execute(
        f"""SELECT ticker, title, url FROM documents
            WHERE source = 'edgar_live:8-K' AND ingested_at > ?
              AND ticker IN ({placeholders})
            ORDER BY ingested_at DESC LIMIT 10""",
        [cutoff, *tickers],
    ).fetchall()
    return [{"ticker": r[0], "title": r[1], "url": r[2]} for r in rows]


def format_briefing() -> str:
    now_sgt = datetime.now(SGT)
    now_et = datetime.now(ET)

    macro = overnight_macro()
    setups_data = json.loads((REPORTS / "swing-setups.json").read_text())
    basis_data = json.loads((REPORTS / "pattern-basis.json").read_text()) if (REPORTS / "pattern-basis.json").exists() else {"summary": {}}
    basis = basis_data.get("summary", {})

    top_setups = setups_data.get("candidates", [])[:6]
    ticker_list = [s["ticker"] for s in top_setups]
    pm = premarket_quotes(ticker_list) if ticker_list else {}

    lines = []
    lines.append("# 🌅 TradingBrain pre-market briefing")
    lines.append(f"_{now_sgt:%a %d %b %H:%M} SGT · {now_et:%H:%M} ET · ~1h to US open_")
    lines.append("")
    lines.append("## Overnight tape")
    sets = [(k, macro.get(k)) for k in ["ES", "NQ", "VIX", "10Y", "DXY", "Nikkei", "HangSeng", "DAX", "Brent"] if macro.get(k)]
    for k, v in sets:
        emoji = "🟢" if v["pct"] > 0 else "🔴" if v["pct"] < 0 else "⚪"
        lines.append(f"- {emoji} **{k}** {v['last']:.2f} ({v['pct']:+.2f}%)")
    lines.append("")

    lines.append("## 🎯 Swing setups — top picks for today's session")
    lines.append("")
    if not top_setups:
        lines.append("_No clean setups today. Cash is a position._")
    for i, s in enumerate(top_setups, 1):
        b = basis.get(s["setup"], {})
        win10 = b.get("winrate_10d")
        med10 = b.get("median_10d")
        n = b.get("n_10d", 0)
        sharpe10 = b.get("sharpe_10d")
        pm_pct = pm.get(s["ticker"], {}).get("pct")
        pm_str = f" · pre-mkt {pm_pct:+.2f}%" if pm_pct is not None else ""
        lines.append(f"### {i}. **{s['ticker']}** · {s['setup']}{pm_str}")
        lines.append(f"- Entry **{s['entry']:.2f}** · Stop **{s['stop']:.2f}** · Target **{s['target']:.2f}** · R {s.get('r_multiple', 0):.1f}")
        lines.append(f"- Reason: {s['reason']}")
        if win10 is not None and n:
            lines.append(f"- Base rate (n={n}): **{win10:.0f}% win rate** at +10d, median {med10:+.2f}%, Sharpe {sharpe10:.2f}")
        lines.append("")

    insider = recent_insider_buys(24)
    if insider:
        lines.append("## 💰 Insider buys (last 24h, > $50k)")
        for ib in insider:
            lines.append(f"- **{ib['ticker']}** — {ib['name']} bought {ib['shares']:,} sh = ${ib['value']:,.0f}")
        lines.append("")

    eights = recent_8ks(24)
    if eights:
        lines.append("## 📄 Fresh 8-Ks (last 24h)")
        for e in eights[:5]:
            lines.append(f"- **{e['ticker']}** — {e['title'][:80]}")
        lines.append("")

    lines.append("## ⚠️ Risk rails")
    lines.append("- Paper-only. Position size ≤ 10%. Risk ≤ 1.5% per trade.")
    lines.append("- Honour stops mechanically. Trail at break-even after +1R.")
    lines.append("- Cash protection: skip all trades if SPY < MA200 (regime check).")
    lines.append("")
    lines.append("🔗 Dashboard: https://lionelsim.zo.space/trading")

    return "\n".join(lines)


def main():
    print("Refreshing pipeline before brief...")
    for cmd in [
        [PY, "-m", "scripts.backfill_10y", "--years", "1"],
        [PY, "-m", "scripts.ingest.web_scrape"],
        [PY, "-m", "scripts.ingest.reddit"],
        [PY, "-m", "scripts.ingest.alphavantage"],
        [PY, "-m", "scripts.ingest.polygon"],
        [PY, "-m", "scripts.ingest.quartr"],
        [PY, "-m", "scripts.ingest.earnings_calendar"],
        [PY, "-m", "scripts.ingest.market_movers"],
        [PY, "-m", "scripts.ingest.intraday_snap"],
        [PY, "scripts/embed.py"],
        [PY, "scripts/build_fts.py"],
        [PY, "scripts/momentum.py"],
        [PY, "-m", "scripts.signals.swing_setup", "--top", "12"],
        [PY, "-m", "loops.desk_signals"],
        [PY, "-m", "loops.signal_tracker", "emit"],
        [PY, "-m", "scripts.brain.decide", "--top", "20"],
        [PY, "-m", "scripts.brain.compile_pages"],
        [PY, "-m", "scripts.brain.entity_graph"],
        [PY, "-m", "scripts.brain.compile_sectors"],
        [PY, "-m", "scripts.brain.hmm_regime"],
        [PY, "-m", "scripts.brain.circuit_breakers"],
        [PY, "-m", "scripts.brain.allocation"],
        [PY, "scripts/broker_alpaca.py"],
        [PY, "-m", "loops.sell_signals"],
    ]:
        rc, out = run(cmd)
        tag = "OK" if rc == 0 else "FAIL"
        print(f"  [{tag}] {' '.join(cmd[1:])}")

    md = format_briefing()
    today = date.today().isoformat()
    (REPORTS / f"premarket-{today}.md").write_text(md)
    (REPORTS / "premarket-latest.md").write_text(md)
    print("\n" + md)


if __name__ == "__main__":
    main()
