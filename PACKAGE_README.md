# TradingBrain — Portable Bundle (for Claude Code)

A quantitative **research + live decision engine** for swing trading US AI-sector
equities. Two halves: a **Research Engine** that validates strategies over 30
years (walk-forward OOS, robustness, significance, cost model), and a **Live
Decision Engine** that only trades what survived — now closed by a **live
forward-test feedback loop** that auto-demotes strategies whose edge decays.

> Scope: **US equities only** (crypto removed). Paper-only. Backtest edge is
> **INDICATIVE** — the universe is survivorship-biased (today's names only).

---

## Quick start (Claude Code)

```bash
# 1. Python deps (3.12+)
pip install duckdb pandas numpy pyyaml yfinance hmmlearn scikit-learn requests

# 2. Verify the data is present (30y daily bars, US tickers)
duckdb data/prices.duckdb -c "SELECT MIN(date), MAX(date), COUNT(DISTINCT ticker), COUNT(*) FROM prices"

# 3. Live single-name analysis (the doctrine engine)
python3 -m scripts.analyze NVDA            # six-lens grade + trade plan
python3 -m scripts.analyze NVDA --json     # machine-readable

# 4. Research a strategy over 30 years
python3 -m backtest.research_engine --all  # Deploy/Iterate/Reject verdicts

# 5. The recursive learning loop
python3 -m backtest.stress_test            # 30y stress test -> calibration.json
python3 -m loops.signal_tracker emit       # log today's buys to the ledger
python3 -m loops.signal_tracker resolve    # mark open signals to market
python3 -m loops.signal_tracker scorecard  # live realized edge -> live-scorecard.json
python3 -m loops.reconcile                 # auto-demote decayed strategies + write lessons
```

The `tb` CLI wraps the common verbs: `bash ../Skills/tradingbrain/scripts/tb.sh analyze NVDA`.

---

## Architecture — how it composes

```
                          DOCTRINE.md  (v2/v3 master doctrine — read this first)
                                  │
   ┌──────────────────────────────┼──────────────────────────────┐
   │  RESEARCH ENGINE             │             LIVE ENGINE       │
   │  backtest/research_engine.py │  scripts/analyze.py (6-lens)  │
   │  backtest/stress_test.py     │  loops/realtime_picks.py      │
   │   → research-report.json     │  loops/desk_signals.py        │
   │   → calibration.json         │   → desk-signals.json         │
   └──────────────┬───────────────┴───────────────┬──────────────┘
                  │   scripts/calibration.py (the trained gate)   │
                  │   • is_enabled / confidence_weight (backtest) │
                  │   • research_verdict / size_cap (Deploy/Iter) │
                  │   • live_gated / live_expectancy (forward)    │
                  └───────────────────┬───────────────────────────┘
                                      │
              ┌───────────────────────┴───────────────────────┐
              │   FEEDBACK LOOP (the part that learns)          │
              │   loops/signal_tracker.py  emit→resolve→score   │
              │     → live-scorecard.json (REAL realized edge)  │
              │   loops/reconcile.py  drift → strategy_library  │
              │     → lessons + failure_log (auto-demote)       │
              └─────────────────────────────────────────────────┘
```

**The key insight to preserve:** the live scorecard caught that VCP (+0.27R backtest)
and BREAKOUT (+0.15R backtest) are **negative live** in the current regime. `reconcile.py`
auto-demoted both to Broken; `calibration.live_gated()` suppresses them at decision time.
This is the difference between a backtest and a learning system.

---

## Directory map

| Path | What it is |
|---|---|
| `DOCTRINE.md` | **Read first.** The master doctrine (six-lens framework, risk laws, trade-plan spec, research lifecycle). |
| `config/session.yaml` | Section 0 operator config — equity, risk %, costs, R/R min, backtest window. Drives sizing + gating. |
| `config/universe.yaml` | US AI-sector universe by theme + regime benchmarks (SPY/QQQ/SMH/^GSPC). |
| `config/holdings.yaml` | Your live positions (read by the sell-side). |
| `scripts/analyze.py` | **Live engine.** Six-lens analysis → grade A/B/C → structure-based trade plan + sizing. |
| `scripts/calibration.py` | The trained gate: backtest edge + research verdict + live drift, all in one. |
| `scripts/brain/hmm_regime.py` | Regime model (HMM, return-ranked labels) → hmm-regime.json. |
| `scripts/signals/swing_setup.py` | Setup detectors (TREND_LEADER, PULLBACK, MEAN_REVERSION, BREAKOUT, VCP, MOMO_CONT). |
| `scripts/ingest/` | Data ingests: prices, intraday snap, earnings calendar, market movers, news, fundamentals. |
| `backtest/research_engine.py` | **Research engine.** IS/OOS/walk-forward + robustness + significance + cost + benchmark → verdict. |
| `backtest/stress_test.py` | 30y full-trade-sim stress test (R-multiples, regime breakdown) → calibration.json. |
| `loops/signal_tracker.py` | **Forward-test feedback.** emit / resolve / scorecard / backfill. |
| `loops/reconcile.py` | Closes the loop: live drift → strategy_library status + lessons. |
| `loops/desk_signals.py` | Pre-computes doctrine-graded buys for the dashboard. |
| `loops/realtime_picks.py` | Regime-gated, earnings-filtered, calibration-weighted picks. |
| `loops/sell_signals.py` | Sell-side: exit urgency on `config/holdings.yaml`. |
| `loops/premarket_briefing.py`, `eod_close.py`, `reflection_weekly.py` | Daily/weekly orchestration loops (full pipeline order). |
| `scripts/collective/` | v3 multi-agent: orchestrator, memory (4 layers), red-team + risk-officer review. |
| `zo-space-routes/` | The dashboard (exported — not on disk in the live system). See below. |
| `export-state/*.csv` | The learned state: signal ledger, strategy library, lessons, failures (portable). |
| `reports/*.json` | All engine outputs (regenerable by re-running the loops). |
| `data/prices.duckdb` | **30y daily OHLCV, US tickers** (~34 MB). The fuel. |

---

## The dashboard (zo-space-routes/)

The live system serves a 10+1-layer real-time desk on a Bun + Hono + Vite host
(zo.space). The routes are **not stored as files** in the live system, so they're
exported here for portability:

- `zo-space-routes/pages/trading-desk.tsx` — the flagship desk (React, polls `/api/desk` every 30s).
- `zo-space-routes/api/desk.ts` — the aggregator that reads `reports/*.json` and serves all 11 layers.

Three supporting routes also live in the space (`/ai-stocks` page, `/api/ai-stocks`
live-quote service with background refresh, `/api/market-movers`). They read the
same `reports/` outputs; re-create them in any Hono server, or ask the assistant
to re-export them.

To run the desk locally in Claude Code, point any Bun+Hono server at these two
files and serve the React page through Vite; the API route reads the JSON in
`reports/`.

---

## Data quality & honesty (do not delete)

- **Survivorship bias:** the universe is today's surviving AI names. Delisted
  losers (dot-com casualties, etc.) are absent, so backtest edge is **overstated**.
  Treat all backtest numbers as *indicative*, not validated. `session.yaml`
  carries the `data_quality` declaration; the engine surfaces it everywhere.
- **Data source:** yfinance daily EOD + a 15-min "snap". No true tick/L2/options flow.
  This is a swing-trading research scaffold, not an HFT system.
- **Paper-only.** Never wire to a live broker without re-validating on
  survivorship-free, point-in-time data and a forward paper run.
- **The live scorecard is the source of truth**, not the backtest. When they
  disagree, believe the scorecard.

---

## Recursive-learning loop (daily cadence)

`premarket_briefing.py` → snap + earnings + movers + regime + swing + desk-signals + `signal_tracker emit`
`eod_close.py` → ingest + swing + `signal_tracker resolve` + `scorecard` + `reconcile`
`reflection_weekly.py` → retrain (stress_test + research_engine) + meta-reflection

Every cycle: emit picks → mark to market → score realized edge → detect drift vs
backtest → auto-demote decayed strategies → distill durable lessons. Inspect any
time: `export-state/lessons.csv`, `export-state/strategy_library.csv`, `reports/live-scorecard.json`.
