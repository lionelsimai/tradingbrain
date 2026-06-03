import json
from pathlib import Path

from lab import live_readiness_dossier


def test_dossier_writes_truthful_blocked_packet(tmp_path: Path):
    (tmp_path / "live-readiness-dashboard.json").write_text(json.dumps({
        "status": "LIVE_BLOCKED",
        "mode": "paper",
        "live_trading_enabled": False,
        "go_live_status": "BLOCKED",
        "paper_evidence_summary": {"paper_resolved": 0, "paper_open": 1, "replay_resolved": 9},
        "blockers": [{"id": "paper_evidence_thin", "severity": "critical"}],
        "research_only_warning": True,
    }))
    (tmp_path / "live-readiness-stress.json").write_text(json.dumps({
        "verdict": "LIVE_BLOCKED",
        "final_decision": "RESEARCH_ONLY",
        "overall_score": 0,
        "execution_score": 100,
        "broker_chaos_score": 100,
    }))
    (tmp_path / "go-live.json").write_text(json.dumps({
        "gates": [{"gate": "5. Paper matches backtest", "status": "FAIL", "detail": "0 paper"}],
        "blockers": ["5. Paper matches backtest"],
    }))

    out = live_readiness_dossier.write_dossier(tmp_path)
    text = out.read_text()

    assert out.name == "live-readiness-dossier.md"
    assert "Final verdict: LIVE_BLOCKED" in text
    assert "Replay/backtest evidence is not counted as forward paper evidence." in text
    assert "| 5. Paper matches backtest | FAIL | 0 paper |" in text
