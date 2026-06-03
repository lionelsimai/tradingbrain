#!/usr/bin/env python3
"""Market Movers — Bloomberg-terminal-style macro & breaking news feed.

Three layers of market-moving signal, ranked by impact:

  1. ECONOMIC CALENDAR (Finnhub /calendar/economic)
       FOMC, CPI/PCE, NFP/Unemployment, GDP, Retail Sales
  2. MACRO NEWS  (Finnhub /news?category=general)
       Fed speakers, Treasury, geopolitics, regulators
  3. AI STOCK NEWS (Finnhub /company-news per universe ticker, batched)
       Upgrades/downgrades, earnings beats/misses, deals

Output: data/market-movers.parquet + reports/market-movers-latest.json
"""
from __future__ import annotations
import os, json, re, time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import requests, pandas as pd, yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
OUT_JSON = ROOT / "reports" / "market-movers-latest.json"
OUT_PARQ = ROOT / "data" / "market-movers.parquet"
UNIV = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
TICKERS = sorted({t for cat in UNIV["universe"].values() for t in cat})
API_KEY = os.environ.get("finnhub") or os.environ.get("FINNHUB_API_KEY")
BASE = "https://finnhub.io/api/v1"

# Impact heuristics — match against headline/event name
HIGH_EVENTS = re.compile(
    r"\b(fomc|fed funds|federal funds|interest rate decision|cpi|core cpi|pce|"
    r"non[- ]?farm payroll|nfp|unemployment rate|gdp(?: growth)?|jolts|"
    r"powell|yellen)\b",
    re.IGNORECASE,
)
MED_EVENTS = re.compile(
    r"\b(retail sales|ism|pmi|consumer confidence|housing starts|"
    r"durable goods|producer prices|ppi|trade balance|fed minutes|"
    r"beige book)\b",
    re.IGNORECASE,
)
HIGH_NEWS = re.compile(
    r"\b(fed|fomc|powell|cpi|inflation|rate cut|rate hike|recession|"
    r"yield curve|tariff|trump|china|sanction|war|attack)\b",
    re.IGNORECASE,
)
TICKER_NEWS_HIGH = re.compile(
    r"\b(beats? estimates?|misses? estimates?|guidance (?:cut|raised|lowered)|"
    r"downgraded|upgraded|acquired|acquisition|merger|takeover|"
    r"investig\w+|lawsuit|halt(?:ed)?|breach|hack|recall|"
    r"earnings (?:beat|miss)|surge|plunge|soar|tumble|"
    r"buy rating|sell rating|price target)\b",
    re.IGNORECASE,
)


def _get(path: str, params: dict) -> dict | list:
    params = {**params, "token": API_KEY}
    r = requests.get(f"{BASE}{path}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()


def fetch_economic_calendar(back_days: int = 1, fwd_days: int = 7) -> list[dict]:
    today = date.today()
    start = (today - timedelta(days=back_days)).isoformat()
    end = (today + timedelta(days=fwd_days)).isoformat()
    try:
        data = _get("/calendar/economic", {"from": start, "to": end})
    except Exception as e:
        print(f"  ! economic calendar failed: {e}")
        return []
    events = data.get("economicCalendar", []) if isinstance(data, dict) else []
    out = []
    for e in events:
        if (e.get("country") or "").upper() != "US":
            continue
        evname = e.get("event", "") or ""
        impact_raw = (e.get("impact") or "").lower()
        if HIGH_EVENTS.search(evname) or impact_raw == "high":
            impact = "HIGH"
        elif MED_EVENTS.search(evname) or impact_raw == "medium":
            impact = "MED"
        else:
            impact = "LOW"
        out.append({
            "kind": "econ",
            "impact": impact,
            "ts": f"{e.get('time') or e.get('date')}",
            "headline": evname,
            "actual": e.get("actual"),
            "estimate": e.get("estimate"),
            "prev": e.get("prev"),
            "unit": e.get("unit"),
            "tickers": [],
            "source": "Finnhub Econ",
            "url": None,
        })
    return out


def fetch_macro_news(hours: int = 24) -> list[dict]:
    try:
        data = _get("/news", {"category": "general"})
    except Exception as e:
        print(f"  ! macro news failed: {e}")
        return []
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    out = []
    for n in data or []:
        if (n.get("datetime") or 0) < cutoff:
            continue
        headline = n.get("headline") or ""
        summary = n.get("summary") or ""
        blob = f"{headline} {summary}"
        if not HIGH_NEWS.search(blob):
            continue
        impact = "HIGH" if HIGH_NEWS.search(headline) else "MED"
        out.append({
            "kind": "macro",
            "impact": impact,
            "ts": datetime.fromtimestamp(n["datetime"], timezone.utc).isoformat(),
            "headline": headline,
            "summary": summary[:200],
            "tickers": [],
            "source": n.get("source") or "—",
            "url": n.get("url"),
        })
    return out


def fetch_ticker_news(hours: int = 24) -> list[dict]:
    """Per-ticker news scan — flag high-impact corporate events on universe names."""
    today = date.today().isoformat()
    start = (date.today() - timedelta(days=2)).isoformat()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
    out = []
    for t in TICKERS:
        try:
            data = _get("/company-news", {"symbol": t, "from": start, "to": today})
        except Exception:
            continue
        for n in data or []:
            if (n.get("datetime") or 0) < cutoff:
                continue
            headline = n.get("headline") or ""
            if not TICKER_NEWS_HIGH.search(headline):
                continue
            out.append({
                "kind": "ticker",
                "impact": "HIGH",
                "ts": datetime.fromtimestamp(n["datetime"], timezone.utc).isoformat(),
                "headline": headline,
                "summary": (n.get("summary") or "")[:200],
                "tickers": [t],
                "source": n.get("source") or "—",
                "url": n.get("url"),
            })
        time.sleep(0.05)  # rate-limit safety
    return out


def dedupe(items: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for it in items:
        key = (it.get("headline", "")[:90].lower(), tuple(it.get("tickers") or []))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def main():
    if not API_KEY:
        print("FINNHUB_API_KEY not set — aborting.")
        return
    print("Market Movers — pulling econ + macro + ticker layers ...")
    econ = fetch_economic_calendar()
    print(f"  econ events:     {len(econ)}")
    macro = fetch_macro_news(24)
    print(f"  macro headlines: {len(macro)}")
    ticker = fetch_ticker_news(24)
    print(f"  ticker events:   {len(ticker)}")

    items = dedupe(econ + macro + ticker)
    # Sort: HIGH first, then by timestamp desc (most recent on top)
    impact_rank = {"HIGH": 0, "MED": 1, "LOW": 2}
    items.sort(key=lambda x: (impact_rank.get(x["impact"], 9), x.get("ts", "")), reverse=False)
    # Within same impact, newer on top
    items.sort(key=lambda x: (impact_rank.get(x["impact"], 9), -1 * _ts_sort_key(x.get("ts", ""))))

    OUT_PARQ.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(items).to_parquet(OUT_PARQ, index=False)

    payload = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "counts": {
            "econ": sum(1 for i in items if i["kind"] == "econ"),
            "macro": sum(1 for i in items if i["kind"] == "macro"),
            "ticker": sum(1 for i in items if i["kind"] == "ticker"),
            "high": sum(1 for i in items if i["impact"] == "HIGH"),
            "total": len(items),
        },
        "items": items[:80],  # cap payload size
    }
    OUT_JSON.write_text(json.dumps(payload, indent=2, default=str))
    print(f"Wrote {len(items)} items → {OUT_JSON}")


def _ts_sort_key(ts: str) -> float:
    try:
        if "T" in ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        # Date-only string from econ calendar
        return datetime.fromisoformat(ts).timestamp() if ts else 0.0
    except Exception:
        return 0.0


if __name__ == "__main__":
    main()
