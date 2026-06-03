# TradingBrain — web app (v1)

A thin, honest front end over the **tested Python recommendation engine**. The
engine computes real picks (entry/stop/target from price structure); this app
stores, displays, and paper-tracks them. The app never asks an LLM to invent
price levels.

## Data flow
```
python3 -m scripts.recommend        # engine produces reports/recommendations.json
python3 -m lab.gauntlet             # validation verdict
python3 -m lab.go_live              # live-gate verdict
python3 -m scripts.export_app       # -> reports/app-export.json (schema-validated)
node app/scripts/ingest-export.mjs  # POST it into the app -> Supabase
```

## Setup
1. `cd app && npm install`
2. Copy `.env.local.example` to `.env.local` and fill in Supabase, `APP_INGEST_TOKEN`, and one data key.
3. Run `app/supabase/schema.sql` in your Supabase SQL editor (creates 4 tables, RLS on).
4. `npm run dev`, open http://localhost:3000.
5. Generate + ingest a run with the data-flow commands above.

## What is verified vs not (honest)
- **Verified (Python, tested):** the engine, the schema-validated export bridge,
  the paper-marking *logic* (mirrors the tested backtester: marks on intraday
  high/low, resolves stop-before-target ties conservatively).
- **NOT run here:** live Supabase, live market-data fetch, the browser UI, and any
  Anthropic call. This code is written to be correct and idiomatic, but you must
  run it in your environment and expect to debug integration details. Treat the
  TypeScript as a reviewed first build, not a battle-tested one.

## Deliberate design choices (see CRITIQUE.md)
- Picks come from the engine, not an LLM, so the risk-defining numbers are real.
- `/api/recommendations` POST refuses any pick that is "strong" while the
  conviction cap is active, or that has a null price level — the app re-checks the
  engine's own safety invariants instead of trusting the payload.
- Write endpoints require `Authorization: Bearer $APP_INGEST_TOKEN` before using
  the Supabase service-role key.
- Paper marking fails safe on missing data (leaves trades open) and never marks
  on a close-only basis.
- RLS is enabled on all tables; add policies for your auth model before exposing
  the app. Do not ship public read/write.
