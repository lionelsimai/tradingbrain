#!/usr/bin/env python3
"""TradingBrain Event Narrative Intelligence report.

Research-only CLI that seeds the current Trump/Dell, Trump/Intel, and
Jensen/Marvell case studies into the narrative scorer. It writes machine-readable
JSON plus a human Markdown brief for TradingBrain review.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from paths import REPORTS_DIR
from scripts.intelligence.event_narrative import EventSource, NarrativeEvent, build_report


OUT_JSON = REPORTS_DIR / "event-narrative-intelligence-latest.json"
OUT_MD = REPORTS_DIR / "event-narrative-intelligence-latest.md"


def seed_events() -> list[NarrativeEvent]:
    return [
        NarrativeEvent(
            title="Trump praises Dell after Dell family Trump Accounts pledge",
            speaker="President Donald Trump",
            event_time_utc="2026-05-08T00:00:00+00:00",
            primary_ticker="DELL",
            observed_price_move_pct=12.0,
            materiality_hint=35.0,
            tags=["trump", "dell", "direct_mention", "ai_infrastructure"],
            event_text=(
                "President Donald Trump thanked Michael and Susan Dell, referenced Dell computer, "
                "told the audience to go out and buy a Dell computer, and linked the praise to "
                "their 6.25 billion dollar Trump Accounts pledge. Dell is also tied to the AI "
                "server and data center infrastructure theme."
            ),
            sources=[
                EventSource(
                    source_name="GovInfo Daily Compilation of Presidential Documents",
                    source_type="official_transcript",
                    source_url="https://www.govinfo.gov/content/pkg/DCPD-202600139/pdf/DCPD-202600139.pdf",
                    timestamp_utc="2026-05-08T00:00:00+00:00",
                    original_quote="Go out and buy a Dell computer. They're great.",
                    quote_confidence=0.98,
                ),
            ],
        ),
        NarrativeEvent(
            title="Dell Federal Systems receives 9.7B Department of War software agreement",
            speaker="Department of War",
            event_time_utc="2026-05-28T00:00:00+00:00",
            primary_ticker="DELL",
            observed_price_move_pct=4.0,
            materiality_hint=78.0,
            tags=["government_contract", "defense", "digital_infrastructure", "dell"],
            event_text=(
                "The Department of War awarded Dell Federal Systems a five-year 9.7 billion "
                "dollar Core Enterprise Technology Agreement for Microsoft services, cloud "
                "subscriptions, on-premises licensing, CJADC2, AI and data analytics support."
            ),
            sources=[
                EventSource(
                    source_name="Department of War News",
                    source_type="official_government_release",
                    source_url=(
                        "https://www.war.gov/News/News-Stories/Article/Article/4502292/"
                        "war-department-signs-97b-technology-deal-with-dell-for-microsoft-services/"
                    ),
                    timestamp_utc="2026-05-28T00:00:00+00:00",
                    original_quote="five-year, $9.7 billion Core Enterprise Technology Agreement to Dell Federal Systems",
                    quote_confidence=0.99,
                ),
            ],
        ),
        NarrativeEvent(
            title="Trump praises Intel government stake and stock rise",
            speaker="President Donald Trump",
            event_time_utc="2026-04-29T22:20:00+00:00",
            primary_ticker="INTC",
            observed_price_move_pct=8.0,
            materiality_hint=52.0,
            tags=["trump", "intel", "policy_tailwind", "us_semiconductor_manufacturing"],
            event_text=(
                "Trump posted that Intel stock continues to rise, said he was proud of Intel, "
                "and credited the United States government equity support for gains. This is a "
                "policy and semiconductor manufacturing catalyst, not a pure AI endorsement."
            ),
            sources=[
                EventSource(
                    source_name="Trump Archive",
                    source_type="official_transcript",
                    source_url="https://trump-archive.com/item/eed30ac1-2454-410f-af07-03ddeacc5dbd",
                    timestamp_utc="2026-04-29T22:20:00+00:00",
                    original_quote="Intel Stock continues to rise.",
                    quote_confidence=0.93,
                ),
                EventSource(
                    source_name="Intel Q1 2026 results",
                    source_type="official_company_release",
                    source_url="https://www.intc.com/news-events/press-releases/detail/1767/intel-reports-first-quarter-2026-financial-results",
                    timestamp_utc="2026-04-23T00:00:00+00:00",
                    original_quote="Data Center and AI (DCAI) revenue was $5.1 billion, up 22%.",
                    quote_confidence=0.98,
                ),
            ],
        ),
        NarrativeEvent(
            title="Jensen Huang calls Marvell the next trillion-dollar company",
            speaker="Jensen Huang",
            event_time_utc="2026-06-02T00:00:00+00:00",
            primary_ticker="MRVL",
            observed_price_move_pct=32.5,
            materiality_hint=68.0,
            tags=["jensen_huang", "marvell", "nvlink_fusion", "ai_networking", "silicon_photonics"],
            event_text=(
                "At Computex, Jensen Huang called Marvell the next trillion-dollar company. "
                "The quote is supported by the prior NVIDIA and Marvell NVLink Fusion strategic "
                "partnership, NVIDIA's 2 billion dollar Marvell investment, custom XPUs, AI-RAN, "
                "scale-up networking, optical interconnect and silicon photonics collaboration."
            ),
            sources=[
                EventSource(
                    source_name="Reuters via Investing.com",
                    source_type="reuters",
                    source_url="https://www.investing.com/news/stock-market-news/marvell-technology-surges-after-nvidias-huang-calls-it-next-trilliondollar-company-4721040",
                    timestamp_utc="2026-06-02T00:00:00+00:00",
                    original_quote="next trillion-dollar company",
                    quote_confidence=0.92,
                ),
                EventSource(
                    source_name="NVIDIA Newsroom",
                    source_type="official_company_release",
                    source_url="https://nvidianews.nvidia.com/news/nvidia-ai-ecosystem-expands-as-marvell-joins-forces-through-nvlink-fusion",
                    timestamp_utc="2026-03-31T00:00:00+00:00",
                    original_quote="NVIDIA has invested $2 billion in Marvell.",
                    quote_confidence=0.99,
                ),
                EventSource(
                    source_name="Marvell Q1 FY2027 results",
                    source_type="official_company_release",
                    source_url="https://investor.marvell.com/news-events/press-releases/detail/1023/marvell-technology-inc-reports-first-quarter-of-fiscal-year-2027-financial-results",
                    timestamp_utc="2026-05-27T00:00:00+00:00",
                    original_quote="exceptional AI-related bookings",
                    quote_confidence=0.97,
                ),
            ],
        ),
    ]


def render_markdown(report: dict) -> str:
    lines = [
        "# TradingBrain Event Narrative Intelligence",
        "",
        f"Generated: {report['asof']}",
        f"Mode: {report['mode']}",
        "",
        f"Paper candidate top 3: {', '.join(report.get('paper_candidate_top3') or []) or 'none'}",
        f"Paper watchlist top 3: {', '.join(report.get('paper_watchlist_top3') or []) or 'none'}",
        "",
        "> Celebrity, CEO, and political statements are catalysts to verify, not automatic buy signals.",
        "",
        "## Ranked Events",
    ]
    for row in report.get("events", []):
        blockers = "; ".join(row.get("blockers") or []) or "none"
        event_types = ", ".join(row.get("event_type") or [])
        lines.extend(
            [
                f"### {row.get('ticker') or 'N/A'} - {row.get('event_title')}",
                f"- Signal: {row.get('final_signal')} | confidence {row.get('confidence_score')} | chase risk {row.get('chase_risk_score')}",
                f"- Event types: {event_types}",
                f"- Source score: {row.get('source_score')} | materiality {row.get('financial_materiality_score')} | directness {row.get('directness_score')}",
                f"- Blockers: {blockers}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def run(*, write: bool = True) -> dict:
    report = build_report(seed_events())
    if write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        OUT_MD.write_text(render_markdown(report))
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate Event Narrative Intelligence report.")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    report = run(write=not args.no_write)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_markdown(report))
        if not args.no_write:
            print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
