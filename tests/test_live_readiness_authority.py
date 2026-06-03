import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from safety import live_readiness


def test_live_readiness_defaults_blocked_without_paper_evidence():
    r = live_readiness.evaluate()
    assert r["live_trading_enabled"] is False
    assert r["go_live_status"] == "BLOCKED"
    assert r["verdict"] == "LIVE_BLOCKED"
    assert any(b["id"] == "paper_evidence_thin" for b in r["blockers"])


def test_live_readiness_hashes_are_present():
    r = live_readiness.evaluate()
    assert r["code_hash"]
    assert r["report_pack_hash"]


def test_live_readiness_uses_live_like_paper_count(monkeypatch):
    monkeypatch.setattr(live_readiness, "_paper_summary", lambda: {
        "paper_resolved": 50,
        "paper_live_like_resolved": 0,
        "paper_live_like_signals": 0,
        "paper_synthetic_quote_signals": 50,
        "paper_open": 0,
        "live_resolved": 0,
        "live_open": 0,
        "replay_resolved": 0,
        "paper_verdict": "synthetic-only",
        "live_verdict": None,
        "replay_verdict": None,
    })

    r = live_readiness.evaluate()
    thin = next(b for b in r["blockers"] if b["id"] == "paper_evidence_thin")

    assert thin["evidence"]["live_like_resolved"] == 0
    assert thin["evidence"]["total_resolved"] == 50
