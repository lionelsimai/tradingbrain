import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lab import live_readiness_stress


def test_stress_runner_writes_truthful_blocked_report(tmp_path):
    rep = live_readiness_stress.run(all_categories=True)
    assert rep["verdict"] == "LIVE_BLOCKED"
    assert rep["paper_evidence_score"] >= 0
    assert rep["readiness"]["live_trading_enabled"] is False
    assert rep["blockers"]
    go_live_case = next(
        c for c in rep["categories"]["commands"]["cases"] if c["scenario"] == "go_live"
    )
    assert go_live_case["status"] == "pass"


def test_stress_report_markdown_has_required_final_format():
    rep = live_readiness_stress.run(all_categories=True)
    md = live_readiness_stress.render_md(rep)
    for label in [
        "Final verdict:", "Current mode:", "Live trading enabled:",
        "Go-live status:", "Paper evidence status:", "Forbidden next action:",
    ]:
        assert label in md
