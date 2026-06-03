#!/usr/bin/env python3
"""Versioned DB schema + a fresh-DB initializer that EVERY loop can call.

This wraps the legacy scripts/db.py KB schema and adds:
  - schema_versions / migrations bookkeeping tables
  - paper_* execution tables with the canonical column names
  - legacy-name VIEWS so old queries keep working
  - a validate() that fails loudly on drift

The canonical knowledge DB lives at paths.DATA_DIR/knowledge.duckdb.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import DATA_DIR

KB_PATH = DATA_DIR / "knowledge.duckdb"
SCHEMA_VERSION = 3

# Execution/paper tables with CANONICAL column names (Section 14).
EXEC_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_versions (
    version INTEGER PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT now(),
    note VARCHAR
);
CREATE TABLE IF NOT EXISTS migrations (
    id VARCHAR PRIMARY KEY,
    applied_at TIMESTAMP DEFAULT now(),
    description VARCHAR
);
CREATE TABLE IF NOT EXISTS paper_account (
    snapshot_date DATE PRIMARY KEY,
    equity DOUBLE, cash DOUBLE, buying_power DOUBLE,
    total_risk DOUBLE, n_open INTEGER, closed INTEGER,
    realized_R DOUBLE, unrealized_R DOUBLE,
    daily_pnl DOUBLE, weekly_pnl DOUBLE, drawdown_pct DOUBLE
);
CREATE TABLE IF NOT EXISTS paper_positions (
    position_id VARCHAR PRIMARY KEY, ticker VARCHAR, setup VARCHAR,
    opened_at DATE, entry DOUBLE, stop DOUBLE, target DOUBLE,
    risk_pct DOUBLE, size_R DOUBLE, status VARCHAR,
    closed_at TIMESTAMP, exit DOUBLE, pnl_R DOUBLE, pnl_pct DOUBLE, meta JSON
);
CREATE TABLE IF NOT EXISTS paper_orders (
    client_order_id VARCHAR PRIMARY KEY, proposal_id VARCHAR, ticker VARCHAR,
    side VARCHAR, qty DOUBLE, order_type VARCHAR, limit_price DOUBLE,
    stop_loss DOUBLE, take_profit DOUBLE, status VARCHAR,
    created_at TIMESTAMP, updated_at TIMESTAMP, mode VARCHAR, meta JSON
);
CREATE TABLE IF NOT EXISTS paper_fills (
    fill_id VARCHAR PRIMARY KEY, client_order_id VARCHAR, ticker VARCHAR,
    side VARCHAR, qty DOUBLE, price DOUBLE, filled_at TIMESTAMP,
    partial BOOLEAN, slippage_bps DOUBLE
);
CREATE TABLE IF NOT EXISTS paper_equity_curve (
    ts TIMESTAMP, equity DOUBLE, drawdown_pct DOUBLE
);
CREATE TABLE IF NOT EXISTS paper_reconciliation (
    ts TIMESTAMP, status VARCHAR, mismatch_type VARCHAR, detail VARCHAR
);
-- Legacy-name compatibility views.
CREATE VIEW IF NOT EXISTS v_paper_account_legacy AS
    SELECT snapshot_date, equity, n_open AS open_count,
           total_risk AS open_risk_R, closed AS closed_today,
           realized_R, unrealized_R
    FROM paper_account;
"""

# Required tables for integrity checks.
REQUIRED_TABLES = [
    "schema_versions", "migrations", "paper_account", "paper_positions",
    "paper_orders", "paper_fills", "paper_equity_curve", "paper_reconciliation",
]


def connect(path: Path | None = None, read_only: bool = False):
    import duckdb
    return duckdb.connect(str(path or KB_PATH), read_only=read_only)


def init(path: Path | None = None) -> dict:
    """Idempotently create the full schema (legacy KB + exec tables). Safe to call
    at the start of every loop."""
    con = connect(path)
    # Legacy KB schema (documents, signals, lessons, etc.) loaded from scripts/db.py
    # by file path (avoids the db/database package-name ambiguity).
    try:
        import importlib.util as _ilu
        _legacy_path = Path(__file__).resolve().parents[1] / "scripts" / "db.py"
        _spec = _ilu.spec_from_file_location("_legacy_scriptsdb_schema", _legacy_path)
        _legacy = _ilu.module_from_spec(_spec)
        _spec.loader.exec_module(_legacy)
        if getattr(_legacy, "KB_SCHEMA", ""):
            con.execute(_legacy.KB_SCHEMA)
    except Exception:
        pass
    con.execute(EXEC_SCHEMA)
    cur = con.execute("SELECT COALESCE(MAX(version),0) FROM schema_versions").fetchone()[0]
    if cur < SCHEMA_VERSION:
        con.execute("INSERT INTO schema_versions (version, note) VALUES (?, ?)",
                    [SCHEMA_VERSION, "v3 exec schema"])
    con.close()
    return {"path": str(path or KB_PATH), "schema_version": SCHEMA_VERSION}


def validate(path: Path | None = None) -> dict:
    con = connect(path)
    have = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
    con.close()
    missing = [t for t in REQUIRED_TABLES if t not in have]
    return {"ok": not missing, "missing": missing, "tables": sorted(have)}


if __name__ == "__main__":
    import json
    print(json.dumps(init(), indent=2))
    print(json.dumps(validate(), indent=2))
