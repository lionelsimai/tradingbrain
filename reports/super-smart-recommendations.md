# TradingBrain Super-Smart US Stock Recommender

Generated: 2026-06-03T01:45:47.910649+00:00
Latest price date: None
Universe scanned: 4
Capability verdict: research_only · score 38/100

## Top research candidates

1. MU — score 68.0 · watch_to_accumulate · ceiling low
   Close: 962.605 · setup: fallback_candidate · upside: 27.1% · RR: 2.0
   Why: Passed strict TradingBrain short-term gate / defined-risk recommender.; Technical scenario has high modeled upside (27.1%).; Reward/risk clears strict threshold (2.00R).
   Gaps: Missing analyst-target provenance; external/banker targets are not trusted.; Fresh fundamental/value-quality evidence missing or stale.; Social/manipulation sentiment unavailable for this ticker.
   Red team: No hard veto found, but still research-only and subject to regime reversal.

2. AAOI — score 45.0 · conditional_watch_only · ceiling low
   Close: None · setup: fallback_candidate · upside: None% · RR: None
   Why: Positive composite pattern score, but evidence stack is incomplete.
   Gaps: Fresh fundamental/value-quality evidence missing or stale.; No fresh news/filing/catalyst document in the last 14 days.; Social/manipulation sentiment unavailable for this ticker.
   Red team: No hard veto found, but still research-only and subject to regime reversal.

3. MRVL — score 45.0 · conditional_watch_only · ceiling low
   Close: None · setup: fallback_candidate · upside: None% · RR: None
   Why: Positive composite pattern score, but evidence stack is incomplete.
   Gaps: Fresh fundamental/value-quality evidence missing or stale.; No fresh news/filing/catalyst document in the last 14 days.; Social/manipulation sentiment unavailable for this ticker.
   Red team: No hard veto found, but still research-only and subject to regime reversal.

4. INTC — score 45.0 · conditional_watch_only · ceiling low
   Close: None · setup: fallback_candidate · upside: None% · RR: None
   Why: Positive composite pattern score, but evidence stack is incomplete.
   Gaps: Fresh fundamental/value-quality evidence missing or stale.; No fresh news/filing/catalyst document in the last 14 days.; Social/manipulation sentiment unavailable for this ticker.
   Red team: No hard veto found, but still research-only and subject to regime reversal.

## Biggest remaining engine gaps
- universe_breadth (critical): configured_universe=77, priced_tickers=81 — Add a liquid-US-stock discovery universe from Polygon/Nasdaq listings, then price/rank at least 500-1500 tradable names.
- point_in_time_survivorship (critical): point_in_time_universe=False, pit_status=open, delisted_included_pct=0.0 — Promote Polygon inactive/corporate-action reference into a survivorship-free PIT universe or import Sharadar/Norgate/Intrinio PIT data.
- forward_paper_evidence (high): forward_paper_trades=3, observations=3, resolved=0 — Keep premarket/EOD paper loops running and require 200+ resolved forward observations across regimes.
- analyst_target_provenance (high): analyst_target_records=0 — Ingest lawful analyst target records with ticker, broker, analyst, rating, target, date, source_url, and independence/dispersion checks.
- fresh_fundamental_catalyst_coverage (medium): fresh_fundamental_ticker_pct=0.0%, fresh_news_ticker_pct=25.0% — Run/expand fundamentals, EDGAR, news, earnings-calendar, and transcript ingestion; require freshness badges on each pick.
- sentiment_manipulation_coverage (medium): social_ticker_pct=0.0% — Continue lawful social sentiment ingestion and require manipulation/euphoria checks on each candidate.

Research-only decision support, not financial advice or an instruction to trade. TradingBrain remains paper/research mode until forward evidence, PIT data, and human review gates improve.
