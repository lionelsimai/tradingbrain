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
technical_target_quality:
  min_reward_risk_for_research_candidate: 1.5
  min_reward_risk_for_clean_candidate: 2.0
"""
    )
    return path


def _candidate(rr_target=130.0):
    return {
        "ticker": "MU",
        "entry_zone": {"low": 100.0, "high": 100.0},
        "stop_loss": 90.0,
        "targets": [{"level": rr_target}],
        "reward_to_risk": (rr_target - 100.0) / 10.0,
    }


def _targets_db(tmp_path, rows=()):
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
    if rows:
        con.executemany("INSERT INTO analyst_targets VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    con.close()
    return db


def test_missing_analyst_provenance_discounts_otherwise_valid_target(tmp_path):
    from scripts.target_quality import build_target_quality_context

    db = _targets_db(tmp_path)
    report = build_target_quality_context(
        candidate_rows=[_candidate()],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "usable_but_discount_confidence"
    assert report["confidence_ceiling"] == "moderate"
    row = report["rows"][0]
    assert row["technical_status"] == "clean"
    assert row["analyst_provenance_status"] == "missing"
    assert any("No analyst-target provenance data" in c for c in row["cautions"])


def test_usable_independent_provenance_supports_clean_target(tmp_path):
    from scripts.target_quality import build_target_quality_context

    rows = [
        ("m1", "MU", "Alpha Securities", "Jane Lee", "buy", "init", 120.0, "2026-05-15", "https://example.com/a", None, "manual", "broker_analyst", None, "2026-05-15"),
        ("m2", "MU", "Beta Capital", "Omar Tan", "buy", "raise", 125.0, "2026-05-16", "https://example.com/b", None, "manual", "broker_analyst", None, "2026-05-16"),
        ("m3", "MU", "Gamma Research", "Rina Koh", "hold", "maintain", 110.0, "2026-05-17", "https://example.com/c", None, "manual", "independent_broker", None, "2026-05-17"),
    ]
    db = _targets_db(tmp_path, rows)

    report = build_target_quality_context(
        candidate_rows=[_candidate()],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "target_supported"
    assert report["confidence_ceiling"] == "moderate"
    row = report["rows"][0]
    assert row["analyst_provenance_status"] == "usable"
    assert row["unique_independent_brokers"] == 3
    assert row["verdict"] == "target_supported"


def test_weak_reward_risk_blocks_target_even_with_provenance(tmp_path):
    from scripts.target_quality import build_target_quality_context

    rows = [
        ("m1", "MU", "Alpha Securities", "Jane Lee", "buy", "init", 120.0, "2026-05-15", "https://example.com/a", None, "manual", "broker_analyst", None, "2026-05-15"),
        ("m2", "MU", "Beta Capital", "Omar Tan", "buy", "raise", 125.0, "2026-05-16", "https://example.com/b", None, "manual", "broker_analyst", None, "2026-05-16"),
        ("m3", "MU", "Gamma Research", "Rina Koh", "hold", "maintain", 110.0, "2026-05-17", "https://example.com/c", None, "manual", "independent_broker", None, "2026-05-17"),
    ]
    db = _targets_db(tmp_path, rows)

    report = build_target_quality_context(
        candidate_rows=[_candidate(rr_target=110.0)],
        knowledge_db=db,
        config_path=_config(tmp_path),
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )

    assert report["verdict"] == "target_untrusted"
    row = report["rows"][0]
    assert row["technical_status"] == "blocked"
    assert row["verdict"] == "target_untrusted"
    assert any("reward:risk" in c for c in row["cautions"])


def test_writer_emits_target_quality_reports(tmp_path, monkeypatch):
    from scripts import target_quality

    db = _targets_db(tmp_path)
    monkeypatch.setattr(target_quality, "REPORTS", tmp_path / "reports")
    monkeypatch.setattr(target_quality, "KB", db)
    monkeypatch.setattr(target_quality, "CONFIG", _config(tmp_path))
    monkeypatch.setattr(target_quality, "OUT_JSON", tmp_path / "reports" / "target-quality-latest.json")
    monkeypatch.setattr(target_quality, "OUT_MD", tmp_path / "reports" / "target-quality-latest.md")

    report = target_quality.build_target_quality_context(
        candidate_rows=[_candidate()],
        knowledge_db=db,
        config_path=target_quality.CONFIG,
        now=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    paths = target_quality.write_reports(report)

    assert (tmp_path / "reports" / "target-quality-latest.json").exists()
    md = (tmp_path / "reports" / "target-quality-latest.md").read_text()
    assert "Target Quality" in md
    assert "MU" in md
    assert paths["markdown"].endswith("target-quality-latest.md")
