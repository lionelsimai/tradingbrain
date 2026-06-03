# Social Sentiment Engine

Multi-source, manipulation-aware social sentiment as a **weak confirmation/veto overlay** — never primary alpha.

## Doctrine

Social sentiment is the noisiest, most adversarial input in the stack. Anyone can post anything; pump rings coordinate; bots flood. So this engine is built to be **hard to fool first, useful second**. It contributes a small, bounded nudge to conviction (±8 points max) and, more importantly, it can **veto** a sentiment tailwind when it smells manufactured.

It is not an alpha source. The repo's own audits (`FLAWS-AND-PROFIT-2026-05-30.md`, `CRITIQUE.md`) are clear: more signals ≠ edge. The one robust edge is the regime filter. Sentiment's job is to (a) avoid chasing manufactured hype, (b) flag euphoria as caution rather than confirmation, and (c) notice when crowd mood and price diverge.

```
documents (any source)                  prices.duckdb
   x: / stocktwits: / reddit:                 |
   news: / provider:<platform>:              (divergence check)
        |                                      |
        v                                      v
  sentiment_lexicon  ──(re-score every post)──> social_sentiment engine
   negation / intensity / hedging                 |
   HYPE + SPAM detection                           ├─ weighted_sentiment (credibility × tier × engagement × recency)
        |                                          ├─ breadth (distinct authors; anon pooled as one)
        |                                          ├─ manipulation_risk  ──(≥0.45 ⇒ VETO; ≥0.25 ⇒ halve)
        |                                          ├─ euphoria_flag      (cap + slight negative = chase risk)
        |                                          ├─ divergence         (price/mood mismatch)
        |                                          └─ confidence         (sample adequacy)
        v                                          v
  {sentiment, intensity, hype, spam}        composite [-1,1] → conviction_points ±8
                                                   |
                                            signals: social_sentiment (+ x_sentiment mirror)
                                            reports/social-sentiment-latest.json
                                                   |
                                            recommend.py sentiment pillar (prefers social; falls back to legacy)
```

## Components

- **`scripts/signals/sentiment_lexicon.py`** — dependency-free finance scorer. Handles negation ("not bullish" flips), intensity ("massive" amplifies), hedging (dampens). Critically, it separates **pump language from genuine bullishness**: phrases like "to the moon / can't lose / 100x / all in", rocket/gem emoji, ticker-stuffing, link-only posts, and ALL-CAPS spam are scored as `hype`/`spam`, not sentiment. High hype shrinks the sentiment it would otherwise produce.
- **`scripts/signals/social_sentiment.py`** — the unified engine. Reads every post in `documents`, re-scores it, and per ticker computes the fields above into a contrarian-aware composite. Writes a `social_sentiment` signal row per ticker (plus a back-compat `x_sentiment` mirror for the X subset) and `reports/social-sentiment-latest.json`. Degrades gracefully on an empty DB (returns neutral, contributes nothing).
- **`config/sentiment_sources.yaml`** — all tunables: source weights, author tiers, veto/dampen thresholds, euphoria thresholds, max conviction points, and the platform compliance posture.
- **`scripts/recommend.py`** — the sentiment pillar now prefers the social engine's bounded `conviction_points` and discloses its read. If a ticker's `manipulation_risk` is high it shows "⚠ manipulation suspected — VETOED" and adds nothing. Stale data contributes nothing. If no social signal exists, it falls back to the legacy X-only path unchanged.

## How the guardrails behave

- **Manufactured pump** (coordinated hype, few authors, near-duplicate text) → `manipulation_risk` high → composite forced to 0. A pump cannot push a pick up.
- **Euphoria** (very high sentiment + volume spike + everyone agreeing) → capped and tilted slightly negative. Unanimous greed is treated as late-cycle chase risk, consistent with the engine's existing contrarian euphoria-fear lens.
- **Divergence** — price rising while mood stays weak reads as distribution (negative); price falling while mood turns up reads as capitulation (mild positive).
- **Thin sample** → low `confidence` shrinks the whole contribution. Anonymous voices are pooled so a single user with many handles can't fake breadth.

## Feeding it (compliant sources only)

```
# StockTwits — official per-symbol API, finance-native, author Bull/Bear tags
python3 -m scripts.ingest.stocktwits --universe        # or --tickers NVDA MU OKLO
#   optional: export STOCKTWITS_TOKEN=...  (raises rate limits)

# X / Twitter — existing credential-safe path (see below on cost)
python3 -m scripts.ingest.x_posts ...

# Reddit — existing OAuth ingester
python3 -m scripts.ingest.reddit ...

# Licensed provider feed (the ONLY compliant path for TruthSocial / Facebook)
python3 -m scripts.ingest.social_provider --file feed.json
#   gated platforms refuse unless you pass --allow-gated AND have a license

# Then build the signal:
python3 -m scripts.signals.social_sentiment
```

The engine reads whatever is in `documents`. You can run one source or all of them; weights handle the blend.

## Platform reality (verified May 2026)

- **X / Twitter** — real FinTwit signal, **enabled**. But pay-per-use is now the default for new developer accounts (roughly $0.005 per post read, ~2M reads/month cap, no free tier; the old Basic/Pro tiers are grandfathered only). Budget the per-read cost, or source X via a licensed data provider.
- **StockTwits** — **enabled** and recommended as the finance-native third source. Official per-symbol API, explicit Bullish/Bearish author labels, high signal-to-noise for tickers.
- **Reddit** — **enabled** via the existing OAuth ingester.
- **TruthSocial** — **off by default, compliance-gated.** No official API; its ToS explicitly forbids scrapers and bots. The only signal worth anything is event-driven posts from a few designated high-impact accounts (policy/tariff/company mentions), and the only lawful way to get them is a licensed provider through `social_provider`. **Never scrape it.**
- **Facebook / Meta** — **off and not recommended.** CrowdTangle is dead; its replacement is academic/non-profit only; the Graph API blocks public-post search; the real chatter sits in private groups. There is no compliant for-profit path and the stock signal is poor. StockTwits fills the "third source" role instead.

A scraper that violates a platform's terms is a legal and operational threat, not a capability. This engine only consumes data you are allowed to have.

## Limits

This module does not change the core finding: TradingBrain is a defensive, regime-driven trend-follower, and the real blockers to going live are a forward paper-trading record and a survivorship-free universe — not signal count. Sentiment makes the system **harder to fool and a little better informed**. It does not make it an alpha machine, and it is informational, not financial advice.
