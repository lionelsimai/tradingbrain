from __future__ import annotations

import json
from pathlib import Path

from scripts import institutional_portfolio


def test_institutional_portfolio_accepts_valid_defined_risk_candidate(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "recommendations.json").write_text(json.dumps({
        "picks": [{
            "ticker": "MU",
            "conviction_score": 75,
            "entry_zone": {"low": 100.0, "high": 100.0},
            "stop_loss": 90.0,
            "targets": [{"level": 120.0}],
        }]
    }))

    report = institutional_portfolio.build_from_reports(equity=100000, report_dir=reports)

    assert report["institutional_risk_budget_ok"] is True
    assert report["portfolio_heat_pct"] == 0.5
    assert report["max_position_risk_pct"] == 0.5
    assert report["accepted_candidates"][0]["ticker"] == "MU"
    assert report["accepted_candidates"][0]["reward_risk"] == 2.0
    assert report["rejected_candidates"] == []


def test_institutional_portfolio_rejects_bad_stop_and_reward_risk(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "recommendations.json").write_text(json.dumps({
        "picks": [{
            "ticker": "NVDA",
            "conviction_score": 80,
            "entry_zone": {"low": 100.0, "high": 100.0},
            "stop_loss": 101.0,
            "targets": [{"level": 101.2}],
        }]
    }))

    report = institutional_portfolio.build_from_reports(equity=100000, report_dir=reports)

    assert report["institutional_risk_budget_ok"] is False
    assert report["accepted_candidates"] == []
    assert "1 candidate(s) rejected by institutional budget checks" in report["blockers"]
    reasons = " ".join(report["rejected_candidates"][0]["reject_reasons"])
    assert "long stop" in reasons


def test_institutional_portfolio_writes_json_and_markdown(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "recommendations.json").write_text(json.dumps({"picks": []}))
    monkeypatch.setattr(institutional_portfolio, "REPORTS", reports)
    monkeypatch.setattr(institutional_portfolio, "OUT_JSON", reports / "institutional.json")
    monkeypatch.setattr(institutional_portfolio, "OUT_MD", reports / "institutional.md")

    paths = institutional_portfolio.write_reports(
        institutional_portfolio.build_from_reports(equity=100000, report_dir=reports)
    )

    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
