#!/usr/bin/env python3
"""Compile one truth page per AI-trade sector. GBrain pattern at higher abstraction."""
from __future__ import annotations
import sys
from datetime import date, datetime, timezone, timedelta
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb, prices

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
OUT = ROOT / "brain" / "sectors"
OUT.mkdir(parents=True, exist_ok=True)
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
SECTORS = UNIVERSE.get("universe", {})

def sector_prices_breadth(pcon, tickers: list[str]) -> dict:
    if not tickers:
        return {}
    ph = ",".join("?" * len(tickers))
    df = pcon.execute(
        f"""SELECT ticker, date, close
            FROM prices WHERE ticker IN ({ph})
            AND date >= (SELECT MAX(date) FROM prices) - INTERVAL 80 DAY
            ORDER BY ticker, date""",
        tickers
    ).fetchdf()
    if df.empty:
        return {"tickers": tickers, "n": 0, "above_ma20": 0, "above_ma50": 0, "leaders": [], "laggards": []}
    out = {"tickers": tickers, "n": 0, "above_ma20": 0, "above_ma50": 0, "leaders": [], "laggards": []}
    rets20 = []
    for t in tickers:
        sub = df[df["ticker"] == t].sort_values("date")
        if len(sub) < 25:
            continue
        out["n"] += 1
        closes = sub["close"].values
        ma20 = closes[-20:].mean()
        last = float(closes[-1])
        if last > ma20: out["above_ma20"] += 1
        if len(closes) >= 50:
            ma50 = closes[-50:].mean()
            if last > ma50: out["above_ma50"] += 1
        if len(closes) >= 21:
            ret20 = (last / float(closes[-21]) - 1) * 100
            rets20.append((t, ret20))
    rets20.sort(key=lambda x: x[1], reverse=True)
    out["leaders"] = rets20[:3]
    out["laggards"] = rets20[-3:][::-1] if len(rets20) > 3 else []
    return out

def sector_signal_summary(kbcon, tickers: list[str]) -> dict:
    if not tickers:
        return {"buys": 0, "watches": 0, "holds": 0, "sells": 0, "top_buys": []}
    ph = ",".join("?" * len(tickers))
    rows = kbcon.execute(
        f"""SELECT ticker, action, confidence
            FROM watchlist
            WHERE ticker IN ({ph})
              AND watchlist_date = (SELECT MAX(watchlist_date) FROM watchlist)
            ORDER BY confidence DESC""",
        tickers,
    ).fetchall()
    counts = {"BUY": 0, "WATCH": 0, "HOLD": 0, "SELL": 0}
    top_buys = []
    for t, a, c in rows:
        if a in counts: counts[a] += 1
        if a == "BUY" and len(top_buys) < 3 and c:
            top_buys.append((t, float(c)))
    return {
        "buys": counts["BUY"], "watches": counts["WATCH"],
        "holds": counts["HOLD"], "sells": counts["SELL"],
        "top_buys": top_buys,
    }

def sector_themes(kbcon, tickers: list[str], days: int = 14) -> list[str]:
    if not tickers:
        return []
    ph = ",".join("?" * len(tickers))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = kbcon.execute(
        f"""SELECT title FROM documents
            WHERE ticker IN ({ph})
            AND COALESCE(published_at, ingested_at) >= ?
            AND title IS NOT NULL AND title != ''
            ORDER BY COALESCE(published_at, ingested_at) DESC
            LIMIT 12""",
        tickers + [cutoff],
    ).fetchall()
    seen, out = set(), []
    for (t,) in rows:
        k = (t or "")[:60]
        if k in seen: continue
        seen.add(k); out.append(t)
    return out[:8]

def render_md(sector: str, tickers: list[str], price: dict, sig: dict, themes: list[str]) -> str:
    breadth20 = price.get("above_ma20", 0)
    breadth50 = price.get("above_ma50", 0)
    n = price.get("n", len(tickers))
    pct20 = (breadth20 / n * 100) if n else 0
    pct50 = (breadth50 / n * 100) if n else 0
    lines = []
    lines.append(f"---\nsector: {sector}\nlast_updated: {datetime.now(timezone.utc).isoformat()}\n"
                 f"n_tickers: {n}\nbreadth_ma20: {pct20:.0f}%\nbreadth_ma50: {pct50:.0f}%\n"
                 f"buys: {sig['buys']}\nholds: {sig['holds']}\n---\n")
    lines.append(f"# {sector.replace('_', ' ').title()}\n")
    lines.append(f"_{n} tickers · breadth above MA20: **{pct20:.0f}%**, MA50: **{pct50:.0f}%**_\n")
    lines.append("## Signal stack")
    lines.append(f"- 🟢 BUY: {sig['buys']}  · 🟡 WATCH: {sig['watches']}  · ⚪ HOLD: {sig['holds']}  · 🔴 SELL: {sig['sells']}")
    if sig["top_buys"]:
        lines.append("- Top BUYs: " + " · ".join([f"**{t}** ({c:.2f})" for t, c in sig["top_buys"]]))
    lines.append("")
    if price.get("leaders"):
        lines.append("## Leaders (20d return)")
        for t, r in price["leaders"]:
            lines.append(f"- **{t}**: {r:+.1f}%")
        lines.append("")
    if price.get("laggards"):
        lines.append("## Laggards (20d return)")
        for t, r in price["laggards"]:
            lines.append(f"- **{t}**: {r:+.1f}%")
        lines.append("")
    if themes:
        lines.append("## Recent themes (last 14d)")
        for t in themes:
            lines.append(f"- {t}")
        lines.append("")
    lines.append("## Constituents")
    lines.append(" · ".join([f"[[{t}]]" for t in tickers]))
    return "\n".join(lines)

def main():
    kbcon = kb()
    pcon = prices()
    n = 0
    for sector, tickers in SECTORS.items():
        if not tickers: continue
        price = sector_prices_breadth(pcon, tickers)
        sig = sector_signal_summary(kbcon, tickers)
        themes = sector_themes(kbcon, tickers)
        md = render_md(sector, tickers, price, sig, themes)
        (OUT / f"{sector}.md").write_text(md)
        n += 1
    print(f"Compiled {n} sector pages → {OUT}")

if __name__ == "__main__":
    main()
