-- TradingBrain app schema (Supabase / Postgres).
-- Refined from the v1 plan to match what the REAL recommendation engine emits
-- (scripts/recommend.py) and to carry the honesty signals the engine produces:
-- conviction band + cap, survivorship state, regime, and the validation verdict.
--
-- Design note: picks are produced by the tested Python engine (real, computed
-- entry/stop/target from price structure), NOT invented by an LLM. The app
-- ingests engine output; an LLM may only narrate, never set price levels.

create table if not exists watchlist (
  id uuid primary key default gen_random_uuid(),
  ticker text not null unique,
  asset_class text default 'equity',
  added_at timestamptz default now()
);

create table if not exists runs (
  id uuid primary key default gen_random_uuid(),
  ran_at timestamptz default now(),
  market_read text,
  tickers_scanned int,
  picks_generated int,
  conviction_cap_active boolean,        -- true while zero live trades (no 'strong')
  live_trades_on_record int,
  gauntlet_verdict text,                -- APPROVED | CONDITIONAL | REJECTED
  go_live_verdict text,                 -- CLEARED FOR LIVE | BLOCKED
  survivorship_warning text,
  disclaimer text
);

create table if not exists recommendations (
  id uuid primary key default gen_random_uuid(),
  run_id uuid references runs(id),
  ticker text not null,
  asset_class text default 'equity',
  direction text,                       -- long | short
  conviction_score int,                 -- capped at 60 while no live track record
  conviction_band text,                 -- strong | moderate | weak
  time_horizon text,
  entry_low numeric, entry_high numeric,
  stop_loss numeric,
  targets jsonb,
  reward_to_risk numeric,
  position_size jsonb,
  thesis text,
  pillar_reads jsonb,
  key_risks jsonb,
  invalidation text,
  confidence_caveats text,              -- carries the cap + missing-pillar disclosure
  data_freshness text,
  created_at timestamptz default now()
);

create table if not exists paper_trades (
  id uuid primary key default gen_random_uuid(),
  recommendation_id uuid references recommendations(id),
  ticker text,
  entry numeric, stop numeric, target numeric,
  status text default 'open',           -- open | hit_target | hit_stop | timeout
  opened_at timestamptz default now(),
  closed_at timestamptz,
  result_r numeric,
  mfe_r numeric,                        -- max favourable excursion (intraday-aware)
  mae_r numeric,                        -- max adverse excursion
  exit_reason text                      -- stop | t1 | t2 | timeout | stop_after_t1
);

-- Honest defaults: lock these down before exposing the app publicly.
alter table watchlist        enable row level security;
alter table runs             enable row level security;
alter table recommendations  enable row level security;
alter table paper_trades     enable row level security;
-- NOTE: add explicit RLS policies for your auth model before deploy. Until then,
-- these tables are owner-only. Do NOT ship public read/write.
