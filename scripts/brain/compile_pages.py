#!/usr/bin/env python3
"""Compile a 'truth page' per ticker. GBrain-style.

The brain answers from compiled pages, not raw RAG. Each ticker gets a
markdown page synthesising: current setup, fundamentals, recent themes,
insider activity, timeline, and a gap analysis of what we DON'T know.
"""
from __future__ import annotations
import json, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
KB = ROOT / "data" / "knowledge.duckdb"
PRICES = ROOT / "data" / "prices.duckdb"
LATEST = ROOT / "reports" / "latest.json"
COMPANIES = ROOT / "brain" / "companies"
UNIVERSE = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

NICE = {
    "gpu_accelerators": "GPU & Accelerators",
    "foundry_packaging": "Foundry & Packaging",
    "memory_storage": "Memory & Storage",
    "eda_design": "EDA & Design",
    "ai_connectivity_optics": "AI Connectivity & Optics",
    "servers_systems": "Servers & Systems",
    "cooling_thermal": "Cooling & Thermal",
    "datacenter_reits": "Data Center REITs",
    "cybersecurity_ai_ops": "Cyber & AI Ops",
    "power_generation": "Power Generation",
    "grid_electrification": "Grid & Electrification",
    "nuclear_smr": "Nuclear / SMR",
    "hyperscalers": "Hyperscalers",
    "ai_native_apps": "AI-native Apps",
    "robotics_autonomy": "Robotics / Autonomy",
    "adjacent_enterprise": "Adjacent Enterprise",
}


def ticker_sector_map():
    out = {}
    for sec, syms in (UNIVERSE.get("universe") or {}).items():
        for t in syms or []:
            out[t] = sec
    return out


def latest_signal_for(ticker: str) -> dict | None:
    if not LATEST.exists():
        return None
    data = json.loads(LATEST.read_text())
    for row in data.get("watchlist", []):
        if row.get("ticker") == ticker:
            return row
    return None


def fundamentals(con, ticker: str) -> dict:
    rows = con.execute(
        """SELECT key, value_num, value_text FROM facts
           WHERE ticker = ? AND kind = 'fundamental'
           ORDER BY as_of DESC""",
        [ticker],
    ).fetchall()
    seen, out = set(), {}
    for k, vn, vt in rows:
        if k in seen:
            continue
        seen.add(k)
        out[k] = vn if vn is not None else vt
    return out


def recent_themes(con, ticker: str, days: int = 30, limit: int = 12) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = con.execute(
        """SELECT source, title, url, ingested_at
           FROM documents
           WHERE ticker = ? AND ingested_at >= ?
           ORDER BY ingested_at DESC LIMIT ?""",
        [ticker, cutoff, limit],
    ).fetchall()
    return [
        {"source": s, "title": (t or "")[:140], "url": u, "at": str(i)[:10]}
        for s, t, u, i in rows
    ]


def insider_summary(con, ticker: str, days: int = 90) -> dict:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    df = con.execute(
        """SELECT transaction_code, COUNT(DISTINCT insider_name) AS people,
                  SUM(total_value) AS dollars, MAX(transaction_date) AS last
           FROM insider_transactions
           WHERE ticker = ? AND transaction_date >= ?
           GROUP BY transaction_code ORDER BY 3 DESC NULLS LAST""",
        [ticker, cutoff],
    ).fetchall()
    return {row[0]: {"people": row[1], "dollars": row[2], "last": str(row[3])} for row in df}


def timeline(con, ticker: str, days: int = 30, limit: int = 15) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = con.execute(
        """SELECT COALESCE(published_at, ingested_at) AS d, source, title FROM documents
           WHERE ticker = ? AND COALESCE(published_at, ingested_at) >= ? AND source LIKE 'edgar%'
           UNION ALL
           SELECT transaction_date, 'form4', insider_name || ' ' || transaction_code || ' ' || COALESCE(CAST(shares AS VARCHAR), '') || ' sh'
           FROM insider_transactions
           WHERE ticker = ? AND transaction_date >= ?
           ORDER BY 1 DESC LIMIT ?""",
        [ticker, cutoff, ticker, cutoff, limit],
    ).fetchall()
    return [{"at": str(d)[:10], "source": s, "what": (t or "")[:120]} for d, s, t in rows]


def last_dates(con, ticker: str) -> dict:
    def first(sql, params):
        r = con.execute(sql, params).fetchone()
        return str(r[0])[:10] if r and r[0] else None
    form = "json_extract_string(metadata, '$.form')"
    return {
        "last_10K": first(f"SELECT MAX(COALESCE(published_at, ingested_at)) FROM documents WHERE ticker=? AND {form}='10-K'", [ticker]),
        "last_10Q": first(f"SELECT MAX(COALESCE(published_at, ingested_at)) FROM documents WHERE ticker=? AND {form}='10-Q'", [ticker]),
        "last_8K":  first(f"SELECT MAX(COALESCE(published_at, ingested_at)) FROM documents WHERE ticker=? AND {form}='8-K'",  [ticker]),
        "last_insider_buy": first(
            "SELECT MAX(transaction_date) FROM insider_transactions WHERE ticker=? AND transaction_code='P'",
            [ticker],
        ),
        "last_x_sentiment": first(
            "SELECT MAX(ingested_at) FROM documents WHERE ticker=? AND source LIKE 'x:%'",
            [ticker],
        ),
        "last_transcript": first(
            "SELECT MAX(ingested_at) FROM documents WHERE ticker=? AND (source LIKE '%transcript%' OR lower(title) LIKE '%transcript%')",
            [ticker],
        ),
        "last_news": first("SELECT MAX(ingested_at) FROM documents WHERE ticker=?", [ticker]),
    }


def gap_analysis(lasts: dict) -> list[str]:
    today = date.today()
    gaps = []
    def age(d):
        if not d:
            return None
        return (today - date.fromisoformat(d)).days
    a = age(lasts.get("last_10K")); 
    if a is None: gaps.append("❌ No 10-K on file in KB.")
    elif a > 400: gaps.append(f"⚠️ 10-K is {a} days old — overdue refresh.")
    a = age(lasts.get("last_10Q"));
    if a is None: gaps.append("❌ No 10-Q on file in KB.")
    elif a > 110: gaps.append(f"⚠️ 10-Q is {a} days old.")
    a = age(lasts.get("last_8K"));
    if a is None: gaps.append("❌ No 8-K on file.")
    a = age(lasts.get("last_transcript"));
    if a is None: gaps.append("❌ No earnings call transcript ingested.")
    a = age(lasts.get("last_x_sentiment"));
    if a is None: gaps.append("❌ No X/FinTwit sentiment yet.")
    elif a > 2: gaps.append(f"⚠️ X sentiment last refreshed {a}d ago.")
    a = age(lasts.get("last_insider_buy"));
    if a is None: gaps.append("ℹ️ No insider *purchases* on file (sells/grants common).")
    a = age(lasts.get("last_news"));
    if a is not None and a > 7: gaps.append(f"⚠️ Latest doc is {a}d old.")
    return gaps


def fmt_fund(f: dict) -> str:
    keys = ["marketCap", "trailingPE", "forwardPE", "priceToSalesTrailing12Months",
            "enterpriseToEbitda", "profitMargins", "grossMargins", "returnOnEquity",
            "freeCashflow", "totalRevenue", "revenueGrowth", "debtToEquity"]
    lines = []
    for k in keys:
        if k in f and f[k] is not None:
            v = f[k]
            try:
                v = float(v)
                if abs(v) > 1e9:
                    label = f"${v/1e9:,.2f}B"
                elif k.endswith("Margins") or k == "returnOnEquity" or k == "revenueGrowth":
                    label = f"{v*100:,.2f}%"
                else:
                    label = f"{v:,.2f}"
            except Exception:
                label = str(v)
            lines.append(f"- **{k}**: {label}")
    return "\n".join(lines) or "_no fundamentals ingested yet_"


def compile_one(con, ticker: str, sector_map: dict) -> Path:
    sec = sector_map.get(ticker, "—")
    nice_sec = NICE.get(sec, sec)
    sig = latest_signal_for(ticker) or {}
    f = fundamentals(con, ticker)
    name = f.get("longName") or f.get("shortName") or ticker
    themes = recent_themes(con, ticker)
    ins = insider_summary(con, ticker)
    tl = timeline(con, ticker)
    lasts = last_dates(con, ticker)
    gaps = gap_analysis(lasts)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # frontmatter
    fm = {
        "ticker": ticker,
        "name": name,
        "sector": sec,
        "last_updated": now,
        "action": sig.get("action"),
        "confidence": sig.get("confidence"),
        "rank": sig.get("rank"),
        "gaps": lasts,
    }
    md = ["---"] + [f"{k}: {json.dumps(v) if isinstance(v, (dict, list)) else v}" for k, v in fm.items()] + ["---", ""]
    md += [f"# {ticker} — {name}", f"*Sector: {nice_sec}*", ""]

    # Current setup
    md += ["## 🎯 Current setup"]
    if sig:
        md += [
            f"- **Action**: `{sig.get('action')}` · confidence **{sig.get('confidence', 0):.0%}** · rank #{sig.get('rank')}",
            f"- **Composite z**: {sig.get('composite', 0):+.2f} = "
            f"momo {sig.get('momentum_z', 0):+.2f} · v+q {sig.get('vq_z', 0):+.2f} · "
            f"insider {sig.get('insider_z', 0):+.2f} · news {sig.get('news_z', 0):+.2f} · "
            f"x {sig.get('x_z', 0):+.2f}",
            f"- **Why**: {sig.get('rationale', '—')}",
        ]
    else:
        md += ["_No current signal row. Run `python3 -m scripts.brain.decide`._"]
    md += [""]

    # Fundamentals
    md += ["## 💰 Fundamentals snapshot", fmt_fund(f), ""]

    # Recent themes
    md += ["## 📰 Recent themes (last 30d)"]
    if themes:
        for t in themes:
            url = f" [↗]({t['url']})" if t["url"] else ""
            md.append(f"- `{t['at']}` _{t['source']}_ — {t['title']}{url}")
    else:
        md.append("_No documents ingested in last 30 days._")
    md.append("")

    # Insider
    md += ["## 👤 Insider activity (last 90d)"]
    if ins:
        for code, info in ins.items():
            label = {"P": "buys", "S": "sells", "A": "awards", "M": "option exercise",
                     "G": "gifts", "F": "tax withhold"}.get(code, code)
            dollars = info.get("dollars")
            d_str = f"${dollars:,.0f}" if dollars else "n/a"
            md.append(f"- **{label}** ({code}) — {info['people']} insider(s) · {d_str} · last {info['last']}")
    else:
        md.append("_No Form 4 activity in window._")
    md.append("")

    # Timeline
    md += ["## 🕒 Timeline (last 30d)"]
    if tl:
        for ev in tl:
            md.append(f"- `{ev['at']}` _{ev['source']}_ — {ev['what']}")
    else:
        md.append("_No timeline events._")
    md.append("")

    # Gap analysis
    md += ["## 🔍 Gap analysis — what the brain does NOT know"]
    if gaps:
        md += [f"- {g}" for g in gaps]
    else:
        md.append("✅ Coverage is current.")
    md.append("")

    md += [f"_Compiled {now}. Source of truth: {ROOT}/data/knowledge.duckdb._"]

    path = COMPANIES / f"{ticker}.md"
    path.write_text("\n".join(md))
    return path


def main() -> int:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", help="compile one ticker only")
    a = p.parse_args()

    con = kb()
    sm = ticker_sector_map()
    tickers = [a.ticker] if a.ticker else sorted(sm.keys())

    print(f"Compiling {len(tickers)} ticker pages → {COMPANIES}/")
    n = 0
    for t in tickers:
        try:
            compile_one(con, t, sm)
            n += 1
        except Exception as e:
            print(f"  [{t}] FAIL {type(e).__name__}: {e}")
    print(f"Done. {n} pages compiled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
