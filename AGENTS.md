# TradingBrain

A personal **recursive-learning** trading research system for an AI-focused
equity universe (50 tickers across compute/semis, networking, hyperscalers,
AI software, power-for-AI, adjacent enterprise). Paper-only until clean
results are demonstrated over months.

## How the recursion works

```
sources → ingest → knowledge.duckdb + raw docs
                          │
                          ▼
                signals (momentum, value+quality, insider, news_burst)
                          │
                          ▼
                brain (fuses + regime-tilts + ranks) → watchlist + decisions
                          │
                          ▼
                daily digest (markdown + Telegram + email)
                          │
                          ▼
            weekly reflection: review → diagnose → propose →
            backtest → adopt only if Sharpe up AND DD not worse
                          │
                          ▼
                rule updates rewrite signal weights / thresholds
```

The agent only adopts changes that survive an out-of-sample backtest.
That gate is the difference between a trading brain and a finance chatbot.

## Dashboard + APIs

Private dashboard at **https://lionelsim.zo.space/trading** (sign-in required).

Routes (zo.space):
- `/trading` — React page with regime card, BUY/WATCH/HOLD/SELL counts, full
  watchlist with per-signal z-score bars (Momo · V+Q · Insider · News · X),
  a sector tab view that colour-codes every ticker by action, signal weights
  and risk rails panels. Reads `/api/tradingbrain/watchlist`.
- `/api/tradingbrain/watchlist` — JSON of `reports/latest.json`, read fresh
  at request time (no cache).
- `/api/tradingbrain/digest` — the latest markdown digest.
- `/api/tradingbrain/ticker/:ticker` — per-ticker deep dive: facts, recent
  documents, insider transactions, signal history. Shells out to `duckdb`.

`reports/latest.json` is written by `scripts/brain/decide.py` every brain run
and contains the dashboard payload (regime, weights, risk rules, per-ticker
rows with sector mapping). `reports/digest-latest.md` is the stable copy of
the daily markdown digest.

## Current state (2026-05-29)

**TradingBrain v2 — two-engine architecture (see `DOCTRINE.md`).**
- **Research Engine** (`backtest/research_engine.py`, `backtest/stress_test.py`):
  validates strategies over 30y with IS/OOS/walk-forward, robustness battery,
  significance tests, cost model, per-regime + benchmark comparison. Emits
  `reports/research-report.json` (Deploy/Iterate/Reject) + `reports/calibration.json`
  + `CALIBRATION-REPORT.md`. **Survivorship-biased universe → results are INDICATIVE.**
- **Live Engine** (`scripts/analyze.py` = `tb analyze <SYM>`): six-lens framework,
  structure-based trade plan + sizing from `config/session.yaml`. Trades ONLY
  strategies the research engine marked Deploy (Iterate → half size, Reject → skip),
  via `scripts/calibration.py`. Regime gate uses a transparent structural read
  (SPY vs MA50/MA200 + drawdown), not the raw HMM label.
- **Verdicts (30y):** MEAN_REVERSION, PULLBACK, TREND_LEADER, VCP = Deploy; BREAKOUT = Iterate.
- Weekly `loops/reflection_weekly.py` retrains both engines.

**Data**
- `data/prices.duckdb` — **407k+ rows OHLCV, 1996 → 2026 (30y), 92 tickers** incl.
  SPY/QQQ/SMH/^GSPC + **11 crypto** (BTC, ETH, SOL, BNB, XRP, NEAR, RENDER, FET, LINK).
- `data/knowledge.duckdb` — 9 tables:
  - `documents` (1.5k+ — RSS, EDGAR, yfinance news; X posts arrive via the daily agent)
  - `facts` (1.2k fundamentals across 80 tickers from yfinance)
  - `insider_transactions` (771 NVDA Form 4 txns; rest of universe backfills Sunday)
  - `macro_series` (2.4k obs: 10Y, 3M, VIX, EUR/USD — yfinance fallback)
  - `signals`, `watchlist`, `decisions`, `hypotheses`, `forecasts`
- `data/momentum.parquet` — latest Clenow rank cache.

**Universe — 80 tickers across 16 sectors:** gpu_accelerators, foundry_packaging,
memory_storage, eda_design, ai_connectivity_optics, servers_systems,
cooling_thermal, datacenter_reits, cybersecurity_ai_ops, power_generation,
grid_electrification, nuclear_smr, hyperscalers, ai_native_apps,
robotics_autonomy, adjacent_enterprise. Full AI-trade stack from silicon
to power to applications.

**X sentiment signal:** `scripts/signals/x_sentiment.py` aggregates
`documents` rows with `source LIKE 'x:%'` (volume_z, sentiment_avg,
engagement_z → composite). `scripts/ingest/x_posts.py` ingests the JSON
the daily agent writes after calling `x_search`. Curated FinTwit handles
live in `config/fintwit_handles.yaml`.

**Latest brain run (2026-05-29):** Regime BULL (0.95). BUYs: TSM (0.81),
NVDA (0.72), MSFT (0.66), AAPL (0.65), GOOGL (0.64), ANET (0.62),
AMAT (0.61), LRCX (0.61). WATCH: IBM, AMZN, AVGO.

## Layout

```
config/
  universe.yaml      # 80 tickers across 16 AI-trade sectors + SPY/QQQ/SMH
  sources.yaml       # trusted source registry, weights, risk rules
  fintwit_handles.yaml  # curated FinTwit accounts for X sentiment ingestion
data/
  prices.duckdb      # OHLCV
  knowledge.duckdb   # documents, facts, signals, watchlist, decisions, ...
  raw/<source>/...   # raw documents on disk (hash-keyed)
  memory/            # reserved for vector store
scripts/
  db.py              # DuckDB helpers + schema (run directly to init)
  ingest.py          # prices (yfinance → prices.duckdb)
  momentum.py        # Clenow momentum rank + regime
  ingest/
    edgar.py         # SEC filings + Form 4 insider transactions
    macro.py         # FRED API (key) or yfinance fallback
    news.py          # RSS aggregators + per-ticker Yahoo news (daily).
    web_scrape.py    # **NEW hourly scraper.** CNBC Markets/Tech,
                     # MarketWatch, PR Newswire, DataCenterDynamics,
                     # DataCenterKnowledge, Investing.com, Hacker News
                     # (AI-keyword filtered), and SEC EDGAR live 8-K +
                     # Form 4 Atom feeds. Filters by the 80-ticker
                     # universe (via CIK map for EDGAR; ticker/keyword
                     # regex for news). Invoked from `loops/hourly_pulse.py`
                     # so every hourly tick adds ~50–150 fresh docs.
                     # Reddit ingest deferred — needs OAuth (PRAW + Reddit
                     # app creds).
    fundamentals.py  # yfinance fundamentals snapshot → facts
    x_posts.py       # ingest X posts JSON written by the daily agent
  signals/
    value_quality.py # P/E, FCF yield, ROE, margins → vq_composite
    events.py        # insider cluster + news burst
    x_sentiment.py   # X chatter volume + sentiment + engagement
  brain/
    decide.py        # fuse signals + regime → watchlist + digest + latest.json
backtest/
  engine.py          # multi-asset backtester with risk rails
loops/
  daily_digest.py    # full pipeline + writes reports/<date>-digest.md
  reflection_weekly.py  # the recursive loop (hypothesise + backtest + gate)
journal/
  journal.py         # CLI for forecasts + calibration tracking
reports/             # markdown digests + backtest CSVs
reference/
  phase1-skeleton/   # original starter (preserved for design reference)
```

## Common commands

```bash
cd /home/workspace/TradingBrain

# Daily pipeline (ingest → score → brain → digest + latest.json):
python3 -m loops.daily_digest

# Just X sentiment (after the daily agent has written data/raw/x/<date>.json):
python3 -m scripts.ingest.x_posts --file data/raw/x/$(date +%F).json
python3 -m scripts.signals.x_sentiment

# Or skip ingest if data is fresh:
python3 -m loops.daily_digest --skip-ingest

# Include EDGAR insider ingest (slower; 90s per ticker for full universe):
python3 -m loops.daily_digest --ingest-edgar

# Weekly reflection (review → hypothesise → backtest → adopt or reject):
python3 -m loops.reflection_weekly

# Backtest a momentum strategy:
python3 -m backtest.engine --start 2024-01-01 --end 2026-05-28 --top 5 --rebalance 21

# Forecast journal:
python3 -m journal.journal forecast NVDA --direction UP --horizon 30 --prob 0.7 --target 200 --reason "data center beat"
python3 -m journal.journal grade
python3 -m journal.journal calibration

# Just one ingest stage:
python3 -m scripts.ingest.edgar --form4-only --since 2025-01-01
python3 -m scripts.ingest.macro --since 2024-01-01
python3 -m scripts.ingest.news --rss-only
python3 -m scripts.ingest.fundamentals
```

## Trusted source registry — see `config/sources.yaml`

Tier 1 (heaviest weight in brain):
- **EDGAR filings** (10-K/Q/8-K) + **Form 4** insider transactions
- **EDGAR 13F** institutional holdings (45d lag)

Tier 2:
- **FRED / Treasury** macro series (rates, VIX, dollar, yield curve)

Tier 3:
- **The Transcript**, **Semianalysis**, **Stratechery** (paid) RSS

Tier 4:
- **Yahoo Finance** per-ticker news, **Capitol Trades** (congress), curated **FinTwit** list

Tier 5:
- **arXiv cs.AI / cs.LG**, **Papers with Code** — relevant for an AI universe

Weights live in `config/sources.yaml > weights:`. Hard risk rules
(stop-loss, take-profit, max position %, kill switch, min confidence)
live in `config/sources.yaml > risk_rules:` and **always override** the brain.

## To do (not yet implemented)

- [ ] Backfill EDGAR Form 4 for full universe (only NVDA so far)
- [ ] Earnings transcripts ingestion (Motley Fool scraping)
- [ ] LLM-driven rationale: feed top-N watchlist + recent KB context into a
      single Anthropic call to produce a 1-paragraph "why" per name
- [ ] Vector store over `documents` for true RAG retrieval at decision time
- [ ] Paper broker that follows the BUY/SELL decisions and tracks PnL daily
- [ ] Deeper hypothesis types in reflection loop (weight-change, signal-add)
- [ ] Earnings calendar awareness (don't add new positions 5d before print)
- [ ] Sector exposure tracker + sector cap enforcement

## Notes for future agents

- **Schema lives in `scripts/db.py`** — change it there, then run
  `python3 scripts/db.py` to re-apply.
- **DuckDB is single-writer** — never run two ingest scripts in parallel.
- **`config/sources.yaml > weights`** is what the brain composes. Touch
  carefully; back any change with a backtest in `loops/reflection_weekly.py`.
- Phase-1 skeleton is in `reference/phase1-skeleton/` — don't import from it;
  it's design source only.
- The brain is intentionally **rule-based** with weighted signals, not an LLM.
  An LLM rationale layer can be bolted on at `scripts/brain/decide.py:decide_action`
  but **rules always have the final call**.

## Research rigor (the `lab/` layer) — read `RIGOR.md`

- **`python3 rebuild.py`** rebuilds everything deterministically and is **gated**:
  it runs a no-look-ahead proof + data-quality check first and halts if they fail.
  Use `--fast` to skip the slow 30y research lifecycle, `--seed N` to set the RNG.
- **`lab/stats.py`** — effective sample size, stationary-bootstrap CIs, Probabilistic
  & Deflated Sharpe (multiple-testing), and PBO via CSCV (overfitting probability).
- **`lab/validate.py`** — proves no look-ahead (corrupts future data, asserts past
  decisions unchanged) and that `detect_at` (backtest) == `detect_setup` (live).
- **`lab/benchmark.py`** — score vs QQQ / equal-weight basket (not SPY): alpha, beta, IR.
- **`lab/data_quality.py`** / **`lab/provenance.py`** — price sanity gate + MANIFEST hashes.
- The research engine now **auto-downgrades Deploy→Iterate** when a strategy's
  Deflated Sharpe < 0.5 or portfolio PBO > 0.5. Single source of truth for the
  trade plan/exit/costs is **`backtest/trade_sim.py`** — used by live, calibration,
  research, and replay alike.
- Reproducibility deps are pinned in **`requirements.txt`**.

## Safety core (the `safety/` layer) — read `docs/runbook.md`

- **Default mode is `paper`. Live FAILS CLOSED** — needs `TB_MODE=live` + `TB_ALLOW_LIVE=1`
  + broker keys + clean kill switch (`safety/config_guard.py`).
- **Every order must pass `safety/risk_gate.check(...)`** — it returns the sized, approved
  `risk_decision`. The AI proposes; the gate decides size; the broker only places what's approved.
- **Kill switch:** `python3 -m safety.operator kill "reason"` / `release`. File-backed at
  `reports/safety_state.json`, fail-closed reads. Granular `pause`/`resume` per strategy/symbol.
- **Audit trail:** `safety/trade_journal.py` (append-only JSONL) reconstructs any trade by
  `client_order_id` (idea→risk→order→fill→exit).
- **Orders are idempotent** (`safety/order.py` deterministic `client_order_id`) — repeated
  signals never double-fill.
- Safety tests: `tests/test_safety.py` (19 critical checks). Never let these go red.

## V3 safety architecture — read `FINAL_BUILD_REPORT.md` + `docs/safety_invariants.md`

- **Canonical risk policy** is `config/risk_policy.yaml` (loaded via `safety/risk_policy.py`).
  It is the ONLY active risk source; session.yaml/sources.yaml risk values are passive.
- **The single order path** is `execution/order_manager.py`. Nothing else may place an order.
  It runs: config_guard → kill_switch → quote_validator → risk_gate → human-review →
  idempotency → `broker_base` adapter (OrderIntent only; live adapter raises). Every step is
  journaled in `journal/event_store.py`.
- **Mode is paper by default; live is disabled** (`docs/live_disabled.md`). Backtest/research/replay never submit.
- **Scorecards are source-separated** (`docs/scorecards.md`): replay/paper never drive the live gate.
- **CI guard** `scripts/ci_static_safety.sh` fails on raw broker writes, hardcoded roots,
  hardcoded equity, agent→broker imports, combined-scorecard gating. Run `make safety`.
- Portable paths via `paths.py` — never hardcode the repo root in `safety/execution/journal/data`.
