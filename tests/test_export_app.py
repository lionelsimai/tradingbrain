#!/usr/bin/env python3
"""Tests for the Python->app bridge — the seam that feeds the web app real,
engine-computed picks instead of LLM-invented ones. Guards the safety invariants
that must survive into the app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import export_app


def test_export_builds_and_validates():
    exp = export_app.build_export()
    problems = export_app.validate(exp)
    assert problems == [], f"export does not match schema: {problems}"


def test_run_carries_verdicts_and_honesty_flags():
    exp = export_app.build_export()
    run = exp["run"]
    # the app must be able to show the validation verdicts and the cap state
    assert "gauntlet_verdict" in run and "go_live_verdict" in run
    assert "conviction_cap_active" in run
    assert "survivorship_warning" in run


def test_no_strong_band_or_null_levels_reach_the_app():
    exp = export_app.build_export()
    cap = exp["run"]["conviction_cap_active"]
    for r in exp["recommendations"]:
        if cap:
            assert r["conviction_band"] != "strong"
        assert r["stop_loss"] is not None and r["entry_low"] is not None


def test_paper_trades_have_valid_status():
    exp = export_app.build_export()
    for t in exp["paper_trades"]:
        assert t["status"] in ("open", "hit_target", "hit_stop", "timeout")


def test_paper_trades_are_forward_only_not_replay():
    exp = export_app.build_export()
    assert exp["evidence_summary"]["paper_trades_are_forward_only"] is True
    for t in exp["paper_trades"]:
        assert t.get("source") != "replay"


def test_replay_trades_are_separate_research_evidence():
    exp = export_app.build_export()
    assert "replay_trades" in exp
    for t in exp["replay_trades"]:
        assert t.get("source") == "replay"


def test_export_uses_read_only_knowledge_connections(monkeypatch):
    import duckdb

    calls = []

    class FakeRows:
        def fetchall(self):
            return []

    class FakeConnection:
        def execute(self, *_args, **_kwargs):
            return FakeRows()

        def close(self):
            pass

    def fake_connect(path, **kwargs):
        calls.append((path, kwargs))
        return FakeConnection()

    monkeypatch.setattr(duckdb, "connect", fake_connect)

    assert export_app._paper_trades() == []
    assert export_app._evidence_summary()["paper_trades_are_forward_only"] is True
    assert calls
    assert all(kwargs.get("read_only") is True for _, kwargs in calls)
