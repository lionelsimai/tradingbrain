from __future__ import annotations

import json
from pathlib import Path

from scripts import event_narrative_intelligence as eni
from scripts.intelligence import event_narrative as core


def _source(source_type: str = "official_company_release") -> core.EventSource:
    return core.EventSource(
        source_name="Test Source",
        source_type=source_type,
        source_url="https://example.com/source",
        timestamp_utc="2026-06-02T00:00:00+00:00",
        original_quote="verified quote",
        quote_confidence=0.95,
    )


def test_source_quality_requires_tier_1_or_2_for_paper_signal():
    weak = core.NarrativeEvent(
        title="Viral rumor",
        speaker="Influencer",
        event_time_utc="2026-06-02T00:00:00+00:00",
        event_text="A viral post says Marvell is an AI infrastructure winner.",
        primary_ticker="MRVL",
        observed_price_move_pct=2.0,
        materiality_hint=80.0,
        sources=[_source("reddit")],
    )

    row = core.score_event(weak)

    assert row["final_signal"] == "blocked_unverified"
    assert row["paper_trade_allowed_by_event_layer"] is False
    assert any("Tier 1 or Tier 2" in blocker for blocker in row["blockers"])


def test_chase_risk_blocks_hot_but_verified_events():
    hot = core.NarrativeEvent(
        title="Verified but already ripped",
        speaker="Jensen Huang",
        event_time_utc="2026-06-02T00:00:00+00:00",
        event_text="Jensen Huang called Marvell the next trillion-dollar company.",
        primary_ticker="MRVL",
        observed_price_move_pct=35.0,
        materiality_hint=80.0,
        sources=[_source("reuters"), _source("official_company_release")],
    )

    row = core.score_event(hot)

    assert row["source_score"] >= 70
    assert row["final_signal"] == "watchlist_wait_for_pullback"
    assert row["paper_trade_allowed_by_event_layer"] is False
    assert any("chase risk" in blocker for blocker in row["blockers"])


def test_verified_material_contract_can_be_paper_candidate():
    contract = core.NarrativeEvent(
        title="Dell government contract",
        speaker="Department of War",
        event_time_utc="2026-05-28T00:00:00+00:00",
        event_text=(
            "The Department of War awarded Dell Federal Systems a 9.7 billion dollar "
            "government contract for AI data analytics, cloud subscriptions and digital infrastructure."
        ),
        primary_ticker="DELL",
        observed_price_move_pct=3.0,
        materiality_hint=85.0,
        sources=[_source("official_government_release")],
    )

    row = core.score_event(contract)

    assert row["final_signal"] == "paper_candidate"
    assert row["paper_trade_allowed_by_event_layer"] is True
    assert "DELL" in row["entities"]["direct_tickers"]


def test_entity_extraction_maps_themes_to_related_tickers():
    entities = core.extract_entities(
        "NVIDIA and Marvell announced NVLink Fusion, custom XPUs, silicon photonics, and AI factories."
    )

    assert "NVDA" in entities["direct_tickers"]
    assert "MRVL" in entities["direct_tickers"]
    assert "LITE" in entities["related_tickers"]
    assert "nvlink fusion" in entities["themes"]


def test_seed_report_ranks_and_writes_artifacts(tmp_path, monkeypatch):
    monkeypatch.setattr(eni, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(eni, "OUT_JSON", tmp_path / "event-narrative-intelligence-latest.json")
    monkeypatch.setattr(eni, "OUT_MD", tmp_path / "event-narrative-intelligence-latest.md")

    report = eni.run(write=True)

    assert report["paper_or_live_orders_submitted"] is False
    assert report["paper_candidate_top3"] == ["DELL"]
    assert "DELL" in report["paper_watchlist_top3"]
    assert "MRVL" in report["paper_watchlist_top3"]
    assert (tmp_path / "event-narrative-intelligence-latest.json").exists()
    assert (tmp_path / "event-narrative-intelligence-latest.md").exists()
    raw = json.loads((tmp_path / "event-narrative-intelligence-latest.json").read_text())
    assert raw["source_policy"]["tier_4_or_5_alone_blocks_trade"] is True


def test_event_narrative_cli_has_no_broker_write_imports():
    src = Path(eni.__file__).read_text() + Path(core.__file__).read_text()

    forbidden = ["OrderManager", "AlpacaPaperAdapter", ".submit(", "submit_order", "requests.post"]
    assert not any(token in src for token in forbidden)
