"""Event Narrative Intelligence.

Scores market-moving public statements and related evidence without creating an
order path. This layer turns speeches, official releases, filings, and trusted
news into auditable paper-watchlist signals. It is intentionally conservative:
weak sources and already-priced moves block trade candidates instead of adding
hype.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


SOURCE_RELIABILITY = {
    "official_transcript": 96,
    "official_company_release": 95,
    "sec_filing": 95,
    "official_government_release": 94,
    "reuters": 92,
    "bloomberg": 92,
    "ap": 90,
    "cnbc": 84,
    "wsj": 84,
    "ft": 84,
    "marketwatch": 78,
    "yahoo_finance": 76,
    "stocktwits": 46,
    "reddit": 34,
    "influencer": 28,
    "anonymous_rumor": 10,
}

SOURCE_TIERS = {
    "official_transcript": 1,
    "official_company_release": 1,
    "sec_filing": 1,
    "official_government_release": 1,
    "reuters": 1,
    "bloomberg": 1,
    "ap": 2,
    "cnbc": 2,
    "wsj": 2,
    "ft": 2,
    "marketwatch": 2,
    "yahoo_finance": 2,
    "stocktwits": 4,
    "reddit": 4,
    "influencer": 4,
    "anonymous_rumor": 5,
}

COMPANY_TICKERS = {
    "dell": "DELL",
    "dell technologies": "DELL",
    "intel": "INTC",
    "marvell": "MRVL",
    "marvell technology": "MRVL",
    "nvidia": "NVDA",
    "advanced micro devices": "AMD",
    "amd": "AMD",
    "broadcom": "AVGO",
    "super micro": "SMCI",
    "supermicro": "SMCI",
    "micron": "MU",
    "hewlett packard enterprise": "HPE",
    "hpe": "HPE",
    "oracle": "ORCL",
    "palantir": "PLTR",
    "tsmc": "TSM",
    "arm": "ARM",
    "qualcomm": "QCOM",
    "arista": "ANET",
    "coherent": "COHR",
    "lumentum": "LITE",
}

THEME_RELATED_TICKERS = {
    "ai servers": ["DELL", "SMCI", "HPE"],
    "ai factory": ["NVDA", "MRVL", "DELL", "SMCI", "AVGO", "ANET"],
    "ai factories": ["NVDA", "MRVL", "DELL", "SMCI", "AVGO", "ANET"],
    "ai infrastructure": ["NVDA", "MRVL", "DELL", "SMCI", "AVGO", "ANET", "HPE", "ORCL"],
    "data center": ["DELL", "SMCI", "HPE", "NVDA", "MRVL", "AVGO", "ANET"],
    "data centers": ["DELL", "SMCI", "HPE", "NVDA", "MRVL", "AVGO", "ANET"],
    "custom xpu": ["MRVL", "AVGO", "AMD", "NVDA"],
    "custom xpus": ["MRVL", "AVGO", "AMD", "NVDA"],
    "custom silicon": ["MRVL", "AVGO", "AMD", "NVDA"],
    "nvlink fusion": ["MRVL", "NVDA"],
    "silicon photonics": ["MRVL", "COHR", "LITE", "AVGO"],
    "optical interconnect": ["MRVL", "COHR", "LITE", "AVGO"],
    "semiconductor manufacturing": ["INTC", "TSM", "MU", "TXN"],
    "u.s. manufacturing": ["INTC", "DELL", "MU"],
    "government contract": ["DELL", "PLTR", "LMT", "RTX", "NOC", "GD"],
    "pentagon": ["DELL", "PLTR", "MSFT"],
    "defense": ["DELL", "PLTR", "LMT", "RTX", "NOC", "GD"],
}

EVENT_TYPE_KEYWORDS = {
    "direct_stock_endorsement": ("buy a", "stock continues to rise", "congratulations to"),
    "ceo_praise": ("next trillion", "trillion-dollar company", "proud of that company"),
    "strategic_partnership": ("partnership", "joins forces", "collaborate", "nvlink fusion"),
    "government_contract": ("contract", "agreement", "blanket purchase", "pentagon"),
    "policy_tailwind": ("reshoring", "u.s. manufacturing", "equity for support", "government stake"),
    "ai_infrastructure": ("ai infrastructure", "ai factory", "ai factories", "data center"),
    "data_center_demand": ("data center", "ai server", "cloud subscription"),
    "supply_chain_bottleneck": ("wafers", "optical", "interconnect", "silicon photonics"),
    "meme_or_social_hype": ("reddit", "stocktwits", "viral"),
}

HIGH_INFLUENCE_SPEAKERS = {
    "donald trump": 95,
    "president donald trump": 95,
    "jensen huang": 96,
    "michael dell": 88,
    "matt murphy": 86,
    "lip-bu tan": 84,
}


@dataclass(frozen=True)
class EventSource:
    source_name: str
    source_url: str
    source_type: str
    timestamp_utc: str
    original_quote: str = ""
    quote_confidence: float = 0.0

    def reliability_score(self) -> int:
        return int(SOURCE_RELIABILITY.get(self.source_type, 35))

    def tier(self) -> int:
        return int(SOURCE_TIERS.get(self.source_type, 5))

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["reliability_score"] = self.reliability_score()
        out["tier"] = self.tier()
        return out


@dataclass(frozen=True)
class NarrativeEvent:
    title: str
    speaker: str
    event_text: str
    event_time_utc: str
    sources: list[EventSource]
    primary_ticker: str | None = None
    observed_price_move_pct: float = 0.0
    materiality_hint: float = 0.0
    tags: list[str] = field(default_factory=list)

    def event_hash(self) -> str:
        payload = "|".join([self.title, self.speaker, self.event_time_utc, self.event_text])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def source_quality(sources: list[EventSource]) -> dict[str, Any]:
    if not sources:
        return {
            "source_score": 0,
            "best_tier": 5,
            "has_tier_1_or_2": False,
            "verified_for_paper": False,
            "source_count": 0,
        }
    scores = [src.reliability_score() for src in sources]
    best_tier = min(src.tier() for src in sources)
    avg = sum(scores) / len(scores)
    best = max(scores)
    multi_source_bonus = min(6, max(0, len({src.source_url for src in sources}) - 1) * 2)
    source_score = min(100, round(0.7 * best + 0.3 * avg + multi_source_bonus, 1))
    has_tier_1_or_2 = any(src.tier() <= 2 for src in sources)
    return {
        "source_score": source_score,
        "best_tier": best_tier,
        "has_tier_1_or_2": has_tier_1_or_2,
        "verified_for_paper": has_tier_1_or_2 and source_score >= 70,
        "source_count": len(sources),
    }


def extract_entities(text: str) -> dict[str, Any]:
    lower = text.lower()
    direct: list[str] = []
    related: list[str] = []
    themes: list[str] = []
    for name, ticker in COMPANY_TICKERS.items():
        if re.search(rf"\b{re.escape(name)}\b", lower) and ticker not in direct:
            direct.append(ticker)
    for theme, tickers in THEME_RELATED_TICKERS.items():
        if theme in lower:
            themes.append(theme)
            for ticker in tickers:
                if ticker not in direct and ticker not in related:
                    related.append(ticker)
    return {
        "direct_tickers": direct,
        "related_tickers": related,
        "themes": themes,
    }


def classify_event(text: str, sources: list[EventSource] | None = None) -> list[str]:
    lower = text.lower()
    out = []
    for event_type, needles in EVENT_TYPE_KEYWORDS.items():
        if any(needle in lower for needle in needles):
            out.append(event_type)
    if sources and any(src.tier() >= 4 for src in sources) and not any(src.tier() <= 2 for src in sources):
        out.append("unverified_or_social_only")
    return out or ["narrative_mention"]


def _speaker_score(speaker: str) -> float:
    return float(HIGH_INFLUENCE_SPEAKERS.get(speaker.lower().strip(), 65))


def _directness_score(primary_ticker: str | None, entities: dict[str, Any]) -> float:
    if primary_ticker and primary_ticker in entities["direct_tickers"]:
        return 100.0
    if primary_ticker and primary_ticker in entities["related_tickers"]:
        return 68.0
    if entities["direct_tickers"]:
        return 85.0
    if entities["related_tickers"]:
        return 55.0
    return 25.0


def _sentiment_score(text: str) -> float:
    lower = text.lower()
    positive = (
        "buy", "great", "congratulations", "proud", "next trillion", "surging",
        "exceptional", "record", "partnership", "investment", "save", "demand",
        "raises", "supports", "enabling",
    )
    negative = ("risk", "concern", "warning", "blocked", "delay", "cuts", "miss")
    score = 50.0
    score += min(35, sum(1 for token in positive if token in lower) * 7)
    score -= min(25, sum(1 for token in negative if token in lower) * 6)
    return max(0.0, min(100.0, score))


def _materiality_score(event_types: list[str], hint: float) -> float:
    base = max(0.0, min(100.0, hint))
    boosts = {
        "government_contract": 28,
        "strategic_partnership": 25,
        "direct_stock_endorsement": 18,
        "policy_tailwind": 16,
        "ai_infrastructure": 14,
        "data_center_demand": 12,
        "ceo_praise": 10,
    }
    for typ in event_types:
        base += boosts.get(typ, 0)
    return max(0.0, min(100.0, base))


def _chase_risk(price_move_pct: float, source_score: float, event_types: list[str]) -> float:
    move = max(0.0, float(price_move_pct))
    risk = min(85.0, move * 2.4)
    if "meme_or_social_hype" in event_types:
        risk += 15
    if source_score < 70:
        risk += 10
    return max(0.0, min(100.0, risk))


def _final_signal(
    confidence: float,
    chase_risk: float,
    source: dict[str, Any],
    event_types: list[str],
    materiality: float,
) -> str:
    if not source["verified_for_paper"]:
        return "blocked_unverified"
    if "unverified_or_social_only" in event_types:
        return "blocked_unverified"
    if chase_risk >= 70:
        return "watchlist_wait_for_pullback"
    if confidence >= 76 and chase_risk < 55:
        return "paper_candidate"
    if (
        confidence >= 70
        and source["source_score"] >= 85
        and materiality >= 85
        and chase_risk < 35
    ):
        return "paper_candidate"
    if confidence >= 62:
        return "paper_watchlist"
    return "no_trade"


def score_event(event: NarrativeEvent) -> dict[str, Any]:
    src = source_quality(event.sources)
    entities = extract_entities(event.event_text)
    event_types = classify_event(event.event_text, event.sources)
    directness = _directness_score(event.primary_ticker, entities)
    sentiment = _sentiment_score(event.event_text)
    materiality = _materiality_score(event_types, event.materiality_hint)
    speaker = _speaker_score(event.speaker)
    price_move = max(0.0, min(100.0, float(event.observed_price_move_pct) * 2.0))
    chase = _chase_risk(event.observed_price_move_pct, src["source_score"], event_types)
    reversal = max(0.0, min(100.0, chase * 0.75 + (100.0 - materiality) * 0.15))
    confidence = (
        0.24 * src["source_score"]
        + 0.18 * directness
        + 0.18 * materiality
        + 0.14 * sentiment
        + 0.10 * speaker
        + 0.08 * min(price_move, 70)
        - 0.17 * chase
    )
    confidence = round(max(0.0, min(100.0, confidence)), 1)
    final_signal = _final_signal(confidence, chase, src, event_types, materiality)
    blockers = []
    if not src["verified_for_paper"]:
        blockers.append("requires at least one Tier 1 or Tier 2 source before paper signal")
    if chase >= 70:
        blockers.append("already-priced/chase risk is high; require pullback or continuation setup")
    if event.primary_ticker is None and not entities["direct_tickers"]:
        blockers.append("no direct ticker mention")
    return {
        "event_id": f"EV-{event.event_hash()}",
        "event_title": event.title,
        "event_summary": event.event_text[:360],
        "speaker": event.speaker,
        "event_time_utc": event.event_time_utc,
        "ticker": event.primary_ticker,
        "event_type": event_types,
        "directness_score": round(directness, 1),
        "novelty_score": 75.0,
        "source_score": src["source_score"],
        "sentiment_score": round(sentiment, 1),
        "financial_materiality_score": round(materiality, 1),
        "price_reaction_score": round(price_move, 1),
        "chase_risk_score": round(chase, 1),
        "reversal_risk_score": round(reversal, 1),
        "confidence_score": confidence,
        "final_signal": final_signal,
        "blocks_auto_trade": True,
        "paper_trade_allowed_by_event_layer": final_signal == "paper_candidate",
        "blockers": blockers,
        "entities": entities,
        "sources": [src_.to_dict() for src_ in event.sources],
        "event_hash": event.event_hash(),
        "tags": event.tags,
    }


def rank_events(events: list[NarrativeEvent]) -> list[dict[str, Any]]:
    rows = [score_event(event) for event in events]
    rows.sort(
        key=lambda row: (
            row["final_signal"] == "paper_candidate",
            row["confidence_score"],
            -row["chase_risk_score"],
        ),
        reverse=True,
    )
    return rows


def build_report(events: list[NarrativeEvent]) -> dict[str, Any]:
    rows = rank_events(events)
    paper_candidates = []
    watchlist = []
    seen = set()
    for row in rows:
        ticker = row.get("ticker")
        if ticker and row.get("paper_trade_allowed_by_event_layer") and ticker not in paper_candidates:
            paper_candidates.append(ticker)
        if ticker and ticker not in seen and row["final_signal"] in {"paper_candidate", "paper_watchlist", "watchlist_wait_for_pullback"}:
            watchlist.append(ticker)
            seen.add(ticker)
    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "engine": "event_narrative_intelligence",
        "mode": "research_and_paper_watchlist_only",
        "paper_or_live_orders_submitted": False,
        "hard_rule": "Celebrity, CEO, and political statements never create blind buy signals.",
        "paper_candidate_top3": paper_candidates[:3],
        "paper_watchlist_top3": watchlist[:3],
        "events": rows,
        "source_policy": {
            "tier_1_or_2_required_for_paper_signal": True,
            "tier_4_or_5_alone_blocks_trade": True,
            "already_priced_high_chase_blocks_entry": True,
        },
    }
