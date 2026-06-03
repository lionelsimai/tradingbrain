from __future__ import annotations

import json
from pathlib import Path

import duckdb

from scripts import pit_coverage


def _wire(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    prices = tmp_path / "prices.duckdb"
    kb = tmp_path / "knowledge.duckdb"
    monkeypatch.setattr(pit_coverage, "REPORTS", reports)
    monkeypatch.setattr(pit_coverage, "PRICES", prices)
    monkeypatch.setattr(pit_coverage, "KB", kb)
    monkeypatch.setattr(pit_coverage, "OUT_JSON", reports / "pit-coverage.json")
    monkeypatch.setattr(pit_coverage, "OUT_MD", reports / "pit-coverage.md")
    return reports, prices, kb


def test_pit_coverage_keeps_traceability_separate_from_pit_closure(tmp_path, monkeypatch):
    reports, prices, kb = _wire(tmp_path, monkeypatch)
    (reports / "recommendations.json").write_text(json.dumps({"picks": [{"ticker": "MU"}]}))
    con = duckdb.connect(str(prices))
    con.execute("CREATE TABLE universe(ticker VARCHAR, category VARCHAR, added_at DATE)")
    con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE, close DOUBLE)")
    con.execute("INSERT INTO universe VALUES ('MU', 'ai', '2026-01-01')")
    con.execute("INSERT INTO prices VALUES ('MU', '2026-01-02', 100.0)")
    con.close()
    duckdb.connect(str(kb)).close()

    report = pit_coverage.compute_pit_coverage()

    assert report["candidate_traceable_pct"] == 100.0
    assert report["status"] == "open"
    assert report["closed"] is False
    assert report["has_vendor_pit_universe"] is False
    assert "universe lacks PIT/delisting columns" in report["blockers"]


def test_pit_coverage_can_close_when_delisted_corporate_actions_and_candidates_trace(tmp_path, monkeypatch):
    reports, prices, kb = _wire(tmp_path, monkeypatch)
    (reports / "recommendations.json").write_text(json.dumps({"picks": [{"ticker": "MU"}]}))
    con = duckdb.connect(str(prices))
    con.execute("CREATE TABLE universe(ticker VARCHAR, active BOOLEAN, delisted_at DATE, added_at DATE)")
    con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE, close DOUBLE)")
    con.execute("INSERT INTO universe VALUES ('MU', true, NULL, '2026-01-01')")
    con.execute("INSERT INTO universe VALUES ('OLD', false, '2024-01-01', '2020-01-01')")
    con.execute("INSERT INTO prices VALUES ('MU', '2026-01-02', 100.0)")
    con.close()
    con = duckdb.connect(str(kb))
    con.execute("CREATE TABLE polygon_splits(ticker VARCHAR, ex_date DATE)")
    con.execute("INSERT INTO polygon_splits VALUES ('MU', '2025-01-01')")
    con.close()

    report = pit_coverage.compute_pit_coverage()

    assert report["status"] == "closed"
    assert report["closed"] is True
    assert report["has_vendor_pit_universe"] is True
    assert report["delisted_rows"] == 1
    assert report["corporate_action_rows"] == 1
    assert report["candidate_traceable_pct"] == 100.0


def test_pit_coverage_writes_json_and_markdown(tmp_path, monkeypatch):
    reports, prices, kb = _wire(tmp_path, monkeypatch)
    con = duckdb.connect(str(prices))
    con.execute("CREATE TABLE universe(ticker VARCHAR)")
    con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE, close DOUBLE)")
    con.close()
    duckdb.connect(str(kb)).close()

    paths = pit_coverage.write_reports()

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
