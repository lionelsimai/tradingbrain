from __future__ import annotations

from datetime import datetime, timezone

import duckdb


def _config(tmp_path):
    path = tmp_path / "target_quality.yaml"
    path.write_text(
        """
freshness:
  max_analyst_target_age_days: 120
  stale_after_days: 60
analyst_target_risk:
  min_independent_brokers_for_confidence: 3
  min_independent_brokers_for_high_confidence: 5
  max_single_source_weight_pct: 40
"""
    )
    return path


def _create_targets_db(tmp_path):
    db = tmp_path / "knowledge.duckdb"
    con = duckdb.connect(str(db))
    con.execute(
        """
        CREATE TABLE analyst_targets(
            target_id VARCHAR, ticker VARCHAR, broker VARCHAR, analyst VARCHAR, rating VARCHAR, action VARCHAR,
            target DOUBLE, date DATE, source_url VARCHAR, notes VARCHAR, provider VARCHAR,
            provenance_level VARCHAR, source_json JSON, ingested_at TIMESTAMP
        )
        """
    )
    return db, con


def test_missing_table_fails_closed(tmp_path):
    from scripts.analyst_target_provenance import build_scorecard, render_md

    db = tmp_path / "knowledge.duckdb"
    duckdb.connect(str(db)).close()

    report = build_scorecard(
        candidate_tickers=["MU"],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "missing"
    assert report["confidence_ceiling"] == "low"
    assert "analyst_targets table missing" in report["blockers"]
    row = report["rows"][0]
    assert row["ticker"] == "MU"
    assert row["status"] == "missing"
    assert row["verdict"] == "do_not_use"
    md = render_md(report)
    assert "- analyst_targets table missing" in md
    assert "\n- none\n" not in md


def test_provider_aggregate_does_not_count_as_independent(tmp_path):
    from scripts.analyst_target_provenance import build_scorecard

    db, con = _create_targets_db(tmp_path)
    con.execute(
        """
        INSERT INTO analyst_targets VALUES
        ('t1','WDC','Finnhub consensus aggregate','aggregate_median','consensus',
         'provider aggregate median target',70,'2026-05-31',
         'https://finnhub.io/api/v1/stock/price-target?symbol=WDC',NULL,'finnhub',
         'provider_aggregate',NULL,'2026-05-31')
        """
    )
    con.close()

    report = build_scorecard(
        candidate_tickers=["WDC"],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "weak"
    assert report["coverage"]["aggregate_only_pct"] == 100.0
    assert report["coverage"]["independent_provenance_pct"] == 0.0
    row = report["rows"][0]
    assert row["status"] == "aggregate_only"
    assert row["recent_aggregate_rows"] == 1
    assert row["recent_independent_rows"] == 0
    assert any("aggregate" in c.lower() for c in row["cautions"])


def test_multiple_independent_brokers_become_usable_research_context(tmp_path):
    from scripts.analyst_target_provenance import build_scorecard

    db, con = _create_targets_db(tmp_path)
    rows = [
        ("m1", "MU", "Alpha Securities", "Jane Lee", "buy", "init", 120.0, "2026-05-15", "https://example.com/a", None, "manual", "broker_analyst", None, "2026-05-15"),
        ("m2", "MU", "Beta Capital", "Omar Tan", "buy", "raise", 125.0, "2026-05-16", "https://example.com/b", None, "manual", "broker_analyst", None, "2026-05-16"),
        ("m3", "MU", "Gamma Research", "Rina Koh", "hold", "maintain", 110.0, "2026-05-17", "https://example.com/c", None, "manual", "independent_broker", None, "2026-05-17"),
    ]
    con.executemany("INSERT INTO analyst_targets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()

    report = build_scorecard(
        candidate_tickers=["MU"],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "usable"
    assert report["confidence_ceiling"] == "moderate"
    assert report["coverage"]["usable_research_context_pct"] == 100.0
    row = report["rows"][0]
    assert row["status"] == "usable"
    assert row["recent_independent_rows"] == 3
    assert row["unique_independent_brokers"] == 3
    assert row["target_median"] == 120.0
    assert row["independent_target_median"] == 120.0
    assert row["target_dispersion_pct"] == 12.5
    assert row["source_concentration_pct"] == 33.3


def test_writer_emits_json_and_markdown(tmp_path, monkeypatch):
    from scripts import analyst_target_provenance as atp

    db, con = _create_targets_db(tmp_path)
    con.execute(
        """
        INSERT INTO analyst_targets VALUES
        ('m1','MU','Alpha Securities','Jane Lee','buy','init',120,'2026-05-15',
         'https://example.com/a',NULL,'manual','broker_analyst',NULL,'2026-05-15')
        """
    )
    con.close()
    monkeypatch.setattr(atp, "KB", db)
    monkeypatch.setattr(atp, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(atp, "CONFIG", _config(tmp_path))
    monkeypatch.setattr(atp, "OUT_JSON", tmp_path / "reports" / "analyst-target-provenance-latest.json")
    monkeypatch.setattr(atp, "OUT_MD", tmp_path / "reports" / "analyst-target-provenance-latest.md")

    report = atp.build_scorecard(
        candidate_tickers=["MU"],
        knowledge_db=db,
        config_path=atp.CONFIG,
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    paths = atp.write_reports(report)

    assert (tmp_path / "reports" / "analyst-target-provenance-latest.json").exists()
    md = (tmp_path / "reports" / "analyst-target-provenance-latest.md").read_text()
    assert "Analyst Target Provenance" in md
    assert "MU" in md
    assert paths["json"].endswith("analyst-target-provenance-latest.json")
