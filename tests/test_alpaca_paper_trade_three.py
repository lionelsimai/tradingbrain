from __future__ import annotations

import json

from scripts import alpaca_paper_trade_three as trade_three


def test_symbols_from_report_prefers_skill_lab_candidates(tmp_path, monkeypatch):
    (tmp_path / "paper-skill-lab-latest.json").write_text(
        json.dumps({"best_skill": {"current_top3": ["MU", "WDC", "AAOI"]}})
    )
    (tmp_path / "quick-3stock-backtest-latest.json").write_text(
        json.dumps({"best_detail": {"current_top3_by_same_score_as_of_latest_date": ["INTC", "MRVL", "AAOI"]}})
    )
    monkeypatch.setattr(trade_three, "REPORTS_DIR", tmp_path)

    assert trade_three._symbols_from_report() == ["MU", "WDC", "AAOI"]


def test_symbols_from_report_prefers_skill_lab_ensemble_over_best_skill(tmp_path, monkeypatch):
    (tmp_path / "paper-skill-lab-latest.json").write_text(
        json.dumps(
            {
                "ensemble_top3": ["NVDA", "AVGO", "MU"],
                "best_skill": {"current_top3": ["AAOI", "MRVL", "INTC"]},
            }
        )
    )
    monkeypatch.setattr(trade_three, "REPORTS_DIR", tmp_path)

    assert trade_three._symbols_from_report() == ["NVDA", "AVGO", "MU"]


def test_symbols_from_report_uses_event_candidate_and_blocks_chase_names(tmp_path, monkeypatch):
    (tmp_path / "event-narrative-intelligence-latest.json").write_text(
        json.dumps(
            {
                "paper_candidate_top3": ["DELL"],
                "events": [
                    {"ticker": "DELL", "final_signal": "paper_candidate"},
                    {"ticker": "MRVL", "final_signal": "watchlist_wait_for_pullback"},
                ],
            }
        )
    )
    (tmp_path / "paper-skill-lab-latest.json").write_text(
        json.dumps({"ensemble_top3": ["AAOI", "MRVL", "LITE"]})
    )
    monkeypatch.setattr(trade_three, "REPORTS_DIR", tmp_path)

    assert trade_three._symbols_from_report() == ["DELL", "AAOI", "LITE"]


def test_symbols_from_report_falls_back_to_quick_backtest(tmp_path, monkeypatch):
    (tmp_path / "quick-3stock-backtest-latest.json").write_text(
        json.dumps({"best_detail": {"current_top3_by_same_score_as_of_latest_date": ["INTC", "MRVL", "AAOI"]}})
    )
    monkeypatch.setattr(trade_three, "REPORTS_DIR", tmp_path)

    assert trade_three._symbols_from_report() == ["INTC", "MRVL", "AAOI"]
