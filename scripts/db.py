"""Shared DuckDB helpers + schema for the knowledge base.

Two databases:
  - data/prices.duckdb     : OHLCV + universe (existing)
  - data/knowledge.duckdb  : everything ingested from trusted sources

This module is import-only; running it directly initialises the schema.
"""
from __future__ import annotations
from pathlib import Path
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES_DB = ROOT / "data" / "prices.duckdb"
KB_DB = ROOT / "data" / "knowledge.duckdb"

KB_SCHEMA = """
-- Raw documents from any source. Hash-keyed for dedup.
CREATE TABLE IF NOT EXISTS documents (
    doc_id        VARCHAR PRIMARY KEY,        -- content sha256
    source        VARCHAR NOT NULL,           -- 'edgar', 'fred', 'rss:reuters', ...
    source_id     VARCHAR,                    -- upstream id (accession #, URL, etc.)
    ticker        VARCHAR,                    -- nullable; macro docs have none
    title         VARCHAR,
    url           VARCHAR,
    published_at  TIMESTAMP,
    ingested_at   TIMESTAMP DEFAULT now(),
    raw_path      VARCHAR,                    -- file on disk under data/raw/
    body          VARCHAR,                    -- extracted plain text (may be NULL for large)
    metadata      JSON
);
CREATE INDEX IF NOT EXISTS idx_docs_ticker_date ON documents(ticker, published_at);
CREATE INDEX IF NOT EXISTS idx_docs_source ON documents(source);

-- Structured facts extracted from documents. The brain reads from here.
CREATE TABLE IF NOT EXISTS facts (
    fact_id       VARCHAR PRIMARY KEY,        -- doc_id + ':' + key
    doc_id        VARCHAR NOT NULL,
    ticker        VARCHAR,
    kind          VARCHAR NOT NULL,           -- 'fundamental','event','insider','macro','sentiment'
    key           VARCHAR NOT NULL,           -- e.g. 'revenue_ttm','insider_buy','guidance_raise'
    value_num     DOUBLE,
    value_text    VARCHAR,
    confidence    DOUBLE DEFAULT 1.0,
    as_of         TIMESTAMP,
    extracted_at  TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_facts_ticker_kind ON facts(ticker, kind);
CREATE INDEX IF NOT EXISTS idx_facts_key ON facts(key);

-- Insider transactions (EDGAR Form 4) — first-class because of signal value.
CREATE TABLE IF NOT EXISTS insider_transactions (
    txn_id          VARCHAR PRIMARY KEY,
    ticker          VARCHAR NOT NULL,
    insider_name    VARCHAR,
    insider_role    VARCHAR,
    transaction_date DATE,
    filed_date      DATE,
    transaction_code VARCHAR,                 -- P=purchase, S=sale, A=award, ...
    shares          DOUBLE,
    price_per_share DOUBLE,
    total_value     DOUBLE,
    shares_after    DOUBLE,
    accession       VARCHAR,
    raw_url         VARCHAR
);
CREATE INDEX IF NOT EXISTS idx_insider_ticker_date ON insider_transactions(ticker, transaction_date);

-- Macro time series (FRED + Treasury).
CREATE TABLE IF NOT EXISTS macro_series (
    series_id     VARCHAR NOT NULL,
    observation_date DATE NOT NULL,
    value         DOUBLE,
    PRIMARY KEY (series_id, observation_date)
);

-- Daily computed signals — one row per ticker per day per signal.
CREATE TABLE IF NOT EXISTS signals (
    signal_date   DATE NOT NULL,
    ticker        VARCHAR NOT NULL,
    signal_name   VARCHAR NOT NULL,
    value         DOUBLE,
    rank          INTEGER,
    metadata      JSON,
    PRIMARY KEY (signal_date, ticker, signal_name)
);

-- Analyst/price-target evidence. Provider aggregates are allowed but must be
-- tagged as provider_aggregate so target-quality checks discount them.
CREATE TABLE IF NOT EXISTS analyst_targets (
    target_id        VARCHAR PRIMARY KEY,
    ticker           VARCHAR NOT NULL,
    broker           VARCHAR,
    analyst          VARCHAR,
    rating           VARCHAR,
    action           VARCHAR,
    target           DOUBLE,
    date             DATE,
    source_url       VARCHAR,
    notes            VARCHAR,
    provider         VARCHAR,
    provenance_level VARCHAR,
    source_json      JSON,
    ingested_at      TIMESTAMP DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_analyst_targets_ticker_date ON analyst_targets(ticker, date);
CREATE INDEX IF NOT EXISTS idx_analyst_targets_provenance ON analyst_targets(provenance_level);

-- The brain's daily watchlist output.
CREATE TABLE IF NOT EXISTS watchlist (
    watchlist_date TIMESTAMP NOT NULL,
    ticker        VARCHAR NOT NULL,
    rank          INTEGER,
    composite_score DOUBLE,
    action        VARCHAR,                    -- BUY / HOLD / SELL / WATCH
    confidence    DOUBLE,
    rationale     VARCHAR,
    signal_breakdown JSON,
    PRIMARY KEY (watchlist_date, ticker)
);

-- Decision log — every recommendation the brain emits, win or lose.
CREATE TABLE IF NOT EXISTS decisions (
    decision_id   VARCHAR PRIMARY KEY,
    decided_at    TIMESTAMP DEFAULT now(),
    ticker        VARCHAR NOT NULL,
    action        VARCHAR NOT NULL,
    price_at_decision DOUBLE,
    confidence    DOUBLE,
    rationale     VARCHAR,
    signal_snapshot JSON,
    kb_citations  JSON,                       -- which doc_ids supported the call
    outcome_price DOUBLE,                     -- filled later
    outcome_at    TIMESTAMP,
    pnl_pct       DOUBLE,
    notes         VARCHAR
);

-- Weekly reflection: hypothesis → backtest → adopted?
CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id VARCHAR PRIMARY KEY,
    proposed_at   TIMESTAMP DEFAULT now(),
    hypothesis    VARCHAR NOT NULL,
    rule_spec     JSON,
    backtest_sharpe DOUBLE,
    backtest_return_pct DOUBLE,
    backtest_max_dd_pct DOUBLE,
    out_of_sample_sharpe DOUBLE,
    adopted       BOOLEAN,
    notes         VARCHAR
);

-- Your forecasts, for calibration tracking.
CREATE TABLE IF NOT EXISTS forecasts (
    forecast_id   VARCHAR PRIMARY KEY,
    made_at       TIMESTAMP DEFAULT now(),
    ticker        VARCHAR,
    horizon_days  INTEGER,
    direction     VARCHAR,                    -- UP / DOWN
    target_price  DOUBLE,
    probability   DOUBLE,                     -- your stated confidence 0-1
    rationale     VARCHAR,
    resolved_at   TIMESTAMP,
    actual_price  DOUBLE,
    correct       BOOLEAN
);

-- Paper-trading account snapshots (one row per day).
CREATE TABLE IF NOT EXISTS paper_account (
    snapshot_date DATE PRIMARY KEY,
    equity        DOUBLE,
    total_risk    DOUBLE,
    n_open        INTEGER,
    closed        INTEGER,
    realized_R    DOUBLE,
    unrealized_R  DOUBLE
);

-- Paper-trading positions (open + closed history).
CREATE TABLE IF NOT EXISTS paper_positions (
    position_id   VARCHAR PRIMARY KEY,
    ticker        VARCHAR,
    setup         VARCHAR,
    opened_at     DATE,
    entry         DOUBLE,
    stop          DOUBLE,
    target        DOUBLE,
    risk_pct      DOUBLE,
    size_R        DOUBLE,
    status        VARCHAR,
    closed_at     TIMESTAMP,
    exit          DOUBLE,
    pnl_R         DOUBLE,
    pnl_pct       DOUBLE,
    meta          JSON
);
"""

def kb() -> duckdb.DuckDBPyConnection:
    """Open knowledge DB, ensuring schema exists."""
    con = duckdb.connect(str(KB_DB))
    try:
        con.execute("INSTALL vss")
        con.execute("LOAD vss")
        con.execute("SET hnsw_enable_experimental_persistence = true")
    except Exception:
        pass
    # Ensure schema exists (idempotent). Previously this was never applied,
    # so a fresh knowledge.duckdb was empty and dependent scripts crashed.
    # Execute the whole script at once (DuckDB supports multi-statement) — the
    # old split(";") silently dropped the `documents` table on a comment edge case.
    try:
        con.execute(KB_SCHEMA)
    except Exception as e:
        import sys as _sys
        print(f"[db.kb] schema init warning: {e}", file=_sys.stderr)
    return con

def prices() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(str(PRICES_DB))

if __name__ == "__main__":
    con = kb()
    print(f"Knowledge DB initialised at {KB_DB}")
    tables = con.execute("SHOW TABLES").fetchall()
    print(f"Tables: {[t[0] for t in tables]}")
    con.close()
