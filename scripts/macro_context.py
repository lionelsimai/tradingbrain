#!/usr/bin/env python3
"""Macro/event context for TradingBrain research mode.

This module keeps macro risk explicit without turning TradingBrain into an
execution system. It can read a small local event calendar plus optional ingested
Truth Social / policy headlines, score whether rate-pricing risk is elevated, and
write a concise report for Hermes to use in stock recommendations.

Input files are optional:
  - config/macro_events.yaml                  taxonomy/rules
  - data/macro/events.json                    user/agent-maintained event calendar
  - data/raw/truthsocial/trump_posts.jsonl    lawfully ingested Trump posts
  - reports/macro-context-latest.json         generated output

The JSON event format is intentionally simple:
{
  "events": [
    {"date": "2026-06-10", "type": "cpi", "title": "May CPI", "importance": "high"}
  ]
}
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    import yaml
except Exception:  # pragma: no cover - repo deps include yaml; graceful CLI fallback
    yaml = None

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists()), Path.cwd())
CONFIG = ROOT / "config" / "macro_events.yaml"
EVENTS = ROOT / "data" / "macro" / "events.json"
TRUTH_POSTS = ROOT / "data" / "raw" / "truthsocial" / "trump_posts.jsonl"
REPORT = ROOT / "reports" / "macro-context-latest.json"

DISCLAIMER = (
    "Macro context is a research overlay only. It may reduce confidence or flag "
    "event risk, but it is not a stand-alone buy/sell signal and never executes trades."
)

RATE_KEYWORDS = {
    "hotter_inflation": ["hot cpi", "inflation reacceler", "sticky inflation", "tariff", "tariffs", "prices up"],
    "cooler_inflation": ["cool cpi", "disinflation", "inflation cooling", "prices down"],
    "hawkish_fed": ["higher for longer", "rate hike", "no cuts", "inflation risk", "hawkish"],
    "dovish_fed": ["rate cut", "cuts", "dovish", "easing", "soft landing"],
    "fed_pressure": ["federal reserve", "fed", "powell", "interest rate", "rates", "rate cuts"],
    "china_tariff": ["china", "tariff", "tariffs", "export control", "semiconductor", "chips", "taiwan"],
    "trade_policy": ["trade deal", "trade war", "import duty", "export ban", "sanction", "sanctions", "customs"],
    "geopolitical_risk": ["israel", "iran", "lebanon", "hezbollah", "russia", "ukraine", "war", "ceasefire", "missile"],
    "fiscal_policy": ["deficit", "debt ceiling", "tax cut", "taxes", "spending bill", "budget"],
    "energy_policy": ["oil", "opec", "energy", "drilling", "pipeline", "gasoline"],
}


@dataclass
class MacroEvent:
    date: str
    type: str
    title: str
    importance: str = "medium"
    source: str | None = None
    url: str | None = None
    notes: str | None = None
    surprise: str | None = None
    rate_bias: str | None = None  # hawkish, dovish, mixed, unknown


def _today(value: str | None = None) -> date:
    if value:
        return date.fromisoformat(value)
    return datetime.now(timezone.utc).date()


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists() or yaml is None:
        return {}
    return yaml.safe_load(path.read_text()) or {}


def load_events(path: Path = EVENTS) -> list[MacroEvent]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text())
    rows = raw.get("events", raw if isinstance(raw, list) else [])
    out: list[MacroEvent] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        try:
            out.append(MacroEvent(
                date=str(r.get("date")),
                type=str(r.get("type", "macro")),
                title=str(r.get("title") or r.get("event") or r.get("type", "macro event")),
                importance=str(r.get("importance", "medium")),
                source=r.get("source"),
                url=r.get("url"),
                notes=r.get("notes"),
                surprise=r.get("surprise"),
                rate_bias=r.get("rate_bias"),
            ))
        except Exception:
            continue
    return out


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        try:
            return datetime.combine(date.fromisoformat(str(s)[:10]), datetime.min.time(), timezone.utc)
        except Exception:
            return None


def _contains_keyword(text: str, keyword: str) -> bool:
    """Match policy terms as words/phrases, not accidental substrings.

    Example: "oil" should not fire inside an unrelated word, and "war" should
    not tag every word containing those letters. This keeps Truth Social policy
    overlays useful instead of noisy.
    """
    phrase = str(keyword or "").strip().lower()
    if not phrase:
        return False
    pattern = r"(?<![a-z0-9])" + re.escape(phrase) + r"(?![a-z0-9])"
    return re.search(pattern, text.lower()) is not None


def _keyword_tags(text: str) -> list[str]:
    low = text.lower()
    tags: list[str] = []
    for tag, words in RATE_KEYWORDS.items():
        if any(_contains_keyword(low, w) for w in words):
            tags.append(tag)
    return tags


def load_truth_social_posts(path: Path = TRUTH_POSTS, *, asof: date | None = None, lookback_days: int = 3) -> list[dict[str, Any]]:
    """Read optional lawfully-ingested Trump/Truth Social posts and tag policy/rate risk.

    We do not scrape. If the local file is absent, the report says unavailable.
    """
    if asof is None:
        asof = _today()
    if not path.exists():
        return []
    start = datetime.combine(asof - timedelta(days=lookback_days), datetime.min.time(), timezone.utc)
    rows: list[dict[str, Any]] = []
    for line in path.read_text(errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        text = str(r.get("text") or r.get("content") or r.get("body") or "")
        dt = _parse_dt(r.get("created_at") or r.get("date") or r.get("timestamp"))
        if dt is None or dt < start:
            continue
        tags = _keyword_tags(text)
        if not tags:
            continue
        rows.append({
            "created_at": dt.isoformat(),
            "source": r.get("source", "truth_social"),
            "url": r.get("url"),
            "text_excerpt": text[:300],
            "tags": tags,
            "rate_pricing_read": _rate_read_from_tags(tags),
        })
    return sorted(rows, key=lambda x: x["created_at"], reverse=True)


def _rate_read_from_tags(tags: list[str]) -> str:
    if "hawkish_fed" in tags or "hotter_inflation" in tags or "china_tariff" in tags or "trade_policy" in tags:
        return "potentially hawkish/inflationary or risk-premium-positive"
    if "geopolitical_risk" in tags:
        return "geopolitical risk-premium headline; monitor oil, USD, yields, and defense/supply-chain exposure"
    if "fiscal_policy" in tags:
        return "fiscal/deficit headline risk; monitor long yields and dollar reaction"
    if "energy_policy" in tags:
        return "energy-price/inflation channel risk; monitor oil and inflation breakevens"
    if "dovish_fed" in tags or "cooler_inflation" in tags:
        return "potentially dovish/disinflationary"
    if "fed_pressure" in tags:
        return "rate-volatility / Fed-independence headline risk"
    return "policy headline risk"


def _catalog_by_type(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(e.get("key")): e for e in config.get("major_event_types", []) if isinstance(e, dict)}


def build_macro_context(*, asof: str | None = None, horizon_days: int = 7) -> dict[str, Any]:
    today = _today(asof)
    config = _load_yaml(CONFIG)
    catalog = _catalog_by_type(config)
    events = load_events()
    truth = load_truth_social_posts(asof=today)

    start = today - timedelta(days=1)
    end = today + timedelta(days=horizon_days)
    upcoming: list[dict[str, Any]] = []
    high_near = False
    for ev in events:
        try:
            d = date.fromisoformat(ev.date[:10])
        except Exception:
            continue
        if not (start <= d <= end):
            continue
        meta = catalog.get(ev.type, {})
        days = (d - today).days
        importance = (ev.importance or meta.get("importance") or "medium").lower()
        if importance == "high" and abs(days) <= 1:
            high_near = True
        upcoming.append({
            **asdict(ev),
            "days_from_asof": days,
            "label": meta.get("label", ev.type),
            "rate_pricing_channel": meta.get("rate_pricing_channel"),
            "watch_fields": meta.get("watch_fields", []),
        })

    # Simple, transparent risk scoring for the research agent.
    score = 0
    drivers: list[str] = []
    for ev in upcoming:
        imp = str(ev.get("importance", "medium")).lower()
        days = abs(int(ev.get("days_from_asof", 99)))
        if imp == "high" and days <= 1:
            score += 3; drivers.append(f"high-impact {ev['label']} within {days} day(s)")
        elif imp == "high" and days <= 3:
            score += 2; drivers.append(f"high-impact {ev['label']} within {days} day(s)")
        elif imp == "medium" and days <= 1:
            score += 1
    if truth:
        score += min(3, len(truth))
        drivers.append(f"{len(truth)} recent Trump/Truth Social policy/rate-sensitive post(s)")

    if score >= 5:
        risk = "high"
        stance = "macro-risk elevated: reduce conviction one notch or wait for event confirmation"
    elif score >= 2:
        risk = "medium"
        stance = "macro-risk present: keep watchlist selective and note rate/yield sensitivity"
    else:
        risk = "low"
        stance = "no known major macro event in the local calendar window; still monitor yields/DXY/QQQ/SMH"

    return {
        "available": True,
        "asof": today.isoformat(),
        "horizon_days": horizon_days,
        "macro_risk": risk,
        "stance": stance,
        "drivers": drivers,
        "upcoming_events": sorted(upcoming, key=lambda x: (x["date"], x.get("importance", ""))),
        "truth_social_policy_posts": truth,
        "truth_social_available": TRUTH_POSTS.exists(),
        "event_calendar_available": EVENTS.exists(),
        "rate_sensitive_markets": config.get("rate_sensitive_markets", []),
        "rules": config.get("risk_rules", []),
        "missing_data": [
            msg for ok, msg in [
                (EVENTS.exists(), "No local data/macro/events.json calendar yet; add FOMC/CPI/PCE/payrolls/ISM/Treasury events or wire a calendar feed."),
                (TRUTH_POSTS.exists(), "No local Truth Social ingestion file yet; add lawful Trump post ingestion to data/raw/truthsocial/trump_posts.jsonl."),
            ] if not ok
        ],
        "disclaimer": DISCLAIMER,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build TradingBrain macro/event context report")
    ap.add_argument("--asof", help="YYYY-MM-DD override")
    ap.add_argument("--horizon-days", type=int, default=7)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="Write reports/macro-context-latest.json")
    args = ap.parse_args(argv)
    out = build_macro_context(asof=args.asof, horizon_days=args.horizon_days)
    if args.write:
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text(json.dumps(out, indent=2, sort_keys=True))
    if args.json:
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print(f"Macro risk: {out['macro_risk']} — {out['stance']}")
        for d in out.get("drivers", []):
            print(f"- {d}")
        for m in out.get("missing_data", []):
            print(f"missing: {m}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
