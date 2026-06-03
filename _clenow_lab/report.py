#!/usr/bin/env python3
"""Daily digest from the latest momentum run."""
from __future__ import annotations
from pathlib import Path
from datetime import datetime, timezone, timedelta
import sys
import yaml
import pandas as pd
import duckdb
import numpy as np

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
DB = ROOT / "data" / "prices.duckdb"
MOM = ROOT / "data" / "momentum.parquet"
UNI_YAML = ROOT / "config" / "universe.yaml"
OUT_DIR = ROOT / "reports"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SGT = timezone(timedelta(hours=8))


def fmt_pct(x: float) -> str:
    return f"{x:+.2f}%" if pd.notna(x) else "—"


def load_category_map() -> dict:
    data = yaml.safe_load(UNI_YAML.read_text())
    out = {}
    for cat, lst in (data.get("universe") or {}).items():
        for t in lst:
            out[t] = cat
    return out


def regime_now(con) -> dict:
    rows = con.execute(
        "SELECT date, adj_close FROM prices WHERE ticker='SPY' ORDER BY date"
    ).fetchdf()
    if rows.empty or len(rows) < 200:
        return {"ok": False, "spy_close": float("nan"), "spy_ma200": float("nan"), "premium_pct": 0.0}
    closes = rows["adj_close"].astype(float).values
    ma200 = float(np.mean(closes[-200:]))
    cur = float(closes[-1])
    return {
        "ok": cur > ma200,
        "spy_close": cur,
        "spy_ma200": ma200,
        "premium_pct": (cur / ma200 - 1) * 100,
    }


def main() -> None:
    if not MOM.exists():
        print("Run momentum.py first.", file=sys.stderr)
        sys.exit(1)
    mom = pd.read_parquet(MOM)
    cat_map = load_category_map()
    mom["category"] = mom["ticker"].map(cat_map).fillna("uncategorized")
    today_sgt = datetime.now(SGT).date()

    con = duckdb.connect(str(DB), read_only=True)
    regime = regime_now(con)
    last2 = con.execute(
        "SELECT ticker, date, adj_close FROM prices WHERE date >= (SELECT MAX(date) - INTERVAL 5 DAY FROM prices) ORDER BY ticker, date"
    ).fetchdf()
    con.close()
    last_dates = sorted(last2["date"].unique())
    d_now = last_dates[-1]
    d_prev = last_dates[-2]
    px_now = last2[last2.date == d_now].set_index("ticker")["adj_close"]
    px_prev = last2[last2.date == d_prev].set_index("ticker")["adj_close"]
    daily_ret = ((px_now / px_prev) - 1.0) * 100
    mom = mom.merge(daily_ret.rename("daily_pct"), left_on="ticker", right_index=True, how="left")
    mom = mom.sort_values("score", ascending=False)

    regime_state = "BULL" if regime["ok"] else "BEAR"

    passing = mom[mom["passes_filters"] == True].head(15)
    rejected_top = mom[~(mom["passes_filters"] == True)].head(5)
    biggest_up = mom.nlargest(5, "daily_pct")
    biggest_dn = mom.nsmallest(5, "daily_pct")

    L = []
    L.append("# Trading Brain — Daily Digest")
    L.append(f"_{today_sgt} SGT · data through {d_now}_")
    L.append("")
    L.append(f"## Regime: **{regime_state}**")
    L.append(f"SPY {regime['spy_close']:.2f} vs 200-day MA {regime['spy_ma200']:.2f} (premium {regime['premium_pct']:+.2f}%)")
    L.append("")
    if not regime["ok"]:
        L.append("> Regime filter is **off**: SPY below its 200-day MA. Default action: hold cash, no new long entries.")
        L.append("")
    L.append("## Top 15 — passes trend + gap filters")
    L.append("")
    L.append("| # | Ticker | Category | Score | Ann% | R² | ATR% | 1-day |")
    L.append("|---|--------|----------|------:|-----:|---:|-----:|------:|")
    for i, r in enumerate(passing.itertuples(), 1):
        cat = (r.category or "").replace("_", " ")
        L.append(
            f"| {i} | {r.ticker} | {cat} | {r.score:.1f} | {r.ann_slope_pct:.1f} | {r.r2:.2f} | {r.atr_pct:.2f} | {fmt_pct(r.daily_pct)} |"
        )
    L.append("")
    L.append("## High scorers blocked by filters")
    L.append("")
    L.append("| Ticker | Score | Why blocked |")
    L.append("|--------|------:|-------------|")
    for r in rejected_top.itertuples():
        reasons = []
        if not r.trend_ok:
            reasons.append("trend (< 100-day MA)")
        if not r.no_big_gap:
            reasons.append("event gap > 15% in 90d")
        L.append(f"| {r.ticker} | {r.score:.1f} | {', '.join(reasons) or '—'} |")
    L.append("")
    L.append("## Biggest movers (1-day)")
    L.append("")
    L.append("**Up:** " + ", ".join(f"{r.ticker} {fmt_pct(r.daily_pct)}" for r in biggest_up.itertuples()))
    L.append("**Down:** " + ", ".join(f"{r.ticker} {fmt_pct(r.daily_pct)}" for r in biggest_dn.itertuples()))
    L.append("")
    L.append("---")
    L.append("_Methodology: Andreas Clenow momentum (90-day exponential regression × R²), regime via SPY 200-day MA, trend via stock 100-day MA, gap filter excludes names with any single-day move > 15% in last 90d. Educational use only — not investment advice._")

    md = "\n".join(L) + "\n"
    out = OUT_DIR / f"{today_sgt}.md"
    out.write_text(md)
    print(str(out))


if __name__ == "__main__":
    main()
