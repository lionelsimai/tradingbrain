from __future__ import annotations

from datetime import datetime, timezone

import duckdb


def _build_dbs(tmp_path):
    kb = tmp_path / "knowledge.duckdb"
    prices = tmp_path / "prices.duckdb"
    con = duckdb.connect(str(prices))
    con.execute("CREATE TABLE prices(ticker VARCHAR, date DATE, open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE)")
    con.execute("""
        INSERT INTO prices VALUES
        ('MU','2026-06-01',100,101,99,100,1000000),
        ('WDC','2026-05-01',50,51,49,50,1000000)
    """)
    con.close()

    con = duckdb.connect(str(kb))
    con.execute("""
        CREATE TABLE facts(
            fact_id VARCHAR, doc_id VARCHAR, ticker VARCHAR, kind VARCHAR, key VARCHAR,
            value_num DOUBLE, value_text VARCHAR, confidence DOUBLE, as_of TIMESTAMP, extracted_at TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE documents(
            doc_id VARCHAR, source VARCHAR, source_id VARCHAR, ticker VARCHAR, title VARCHAR, url VARCHAR,
            published_at TIMESTAMP, ingested_at TIMESTAMP, raw_path VARCHAR, body VARCHAR, metadata JSON
        )
    """)
    con.execute("CREATE TABLE signals(signal_date DATE, ticker VARCHAR, signal_name VARCHAR, value DOUBLE, rank INTEGER, metadata JSON)")
    con.execute("""
        CREATE TABLE analyst_targets(
            target_id VARCHAR, ticker VARCHAR, broker VARCHAR, analyst VARCHAR, rating VARCHAR, action VARCHAR,
            target DOUBLE, date DATE, source_url VARCHAR, notes VARCHAR, provider VARCHAR,
            provenance_level VARCHAR, source_json JSON, ingested_at TIMESTAMP
        )
    """)
    con.execute("""
        INSERT INTO facts VALUES
        ('f1','d1','MU','fundamental','roe',1.0,NULL,1.0,'2026-05-20','2026-05-20'),
        ('f2','d2','WDC','fundamental','roe',1.0,NULL,1.0,'2025-12-31','2025-12-31')
    """)
    con.execute("""
        INSERT INTO documents VALUES
        ('d1','news','n1','MU','fresh MU',NULL,'2026-05-31','2026-05-31',NULL,'',NULL),
        ('d2','news','n2','WDC','old WDC',NULL,'2026-04-01','2026-04-01',NULL,'',NULL)
    """)
    con.execute("INSERT INTO signals VALUES ('2026-05-31','MU','social_sentiment',0.5,1,NULL)")
    con.execute("INSERT INTO analyst_targets VALUES ('t1','MU','Broker','Analyst','buy','init',120,'2026-05-15','https://example.com',NULL,'manual','independent_broker',NULL,'2026-05-15')")
    con.execute("INSERT INTO analyst_targets VALUES ('t2','WDC','Finnhub consensus aggregate','aggregate_median','consensus','provider aggregate median target',70,'2026-05-31','https://finnhub.io/api/v1/stock/price-target?symbol=WDC',NULL,'finnhub','provider_aggregate',NULL,'2026-05-31')")
    con.close()
    return kb, prices


def test_data_freshness_scorecard_badges_candidates_without_fetching(tmp_path):
    from scripts.data_freshness import build_data_freshness_scorecard

    kb, prices = _build_dbs(tmp_path)
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    report = build_data_freshness_scorecard(
        ["MU", "WDC"], knowledge_db=kb, prices_db=prices, now=now
    )

    assert report["mode"] == "candidate_data_freshness_scorecard_v1"
    assert report["status"] == "stale_or_missing_critical"
    assert report["coverage"]["candidate_count"] == 2
    assert report["coverage"]["price_fresh_pct"] == 50.0
    assert report["coverage"]["fundamentals_fresh_pct"] == 50.0
    assert report["coverage"]["news_fresh_pct"] == 50.0
    assert report["coverage"]["analyst_target_any_recent_pct"] == 100.0
    assert report["coverage"]["analyst_target_independent_present_pct"] == 50.0
    assert report["coverage"]["analyst_target_aggregate_only_pct"] == 50.0
    rows = {r["ticker"]: r for r in report["rows"]}
    assert rows["MU"]["badge"] == "green"
    assert rows["MU"]["analyst_target_age_days"] == 17
    assert rows["MU"]["analyst_target_independent_recent_rows"] == 1
    assert rows["WDC"]["badge"] == "red"
    assert rows["WDC"]["analyst_target_recent_rows"] == 1
    assert rows["WDC"]["analyst_target_independent_recent_rows"] == 0
    assert rows["WDC"]["analyst_target_aggregate_recent_rows"] == 1
    assert "price" in rows["WDC"]["missing_or_stale"]
    assert "news" in rows["WDC"]["missing_or_stale"]
    assert "analyst_target_independent_provenance" in rows["WDC"]["missing_or_stale"]


def test_data_freshness_writer_emits_json_and_markdown(tmp_path, monkeypatch):
    from scripts import data_freshness

    kb, prices = _build_dbs(tmp_path)
    monkeypatch.setattr(data_freshness, "REPORTS_DIR", tmp_path / "reports")
    report = data_freshness.build_data_freshness_scorecard(
        ["MU"], knowledge_db=kb, prices_db=prices, now=datetime(2026, 6, 1, tzinfo=timezone.utc), write=True
    )

    assert report["coverage"]["green_badge_pct"] == 100.0
    md = (tmp_path / "reports" / "data-freshness-latest.md").read_text()
    assert "Candidate Data Freshness" in md
    assert "Independent analyst target provenance" in md
    assert "MU" in md
    assert (tmp_path / "reports" / "data-freshness-latest.json").exists()
