from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestResult
from scripts import paper_skill_lab as lab


def _fake_result(*, final_equity: float, return_pct: float, max_dd: float, halted: bool = False):
    return BacktestResult(
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        initial_equity=100_000.0,
        final_equity=final_equity,
        return_pct=return_pct,
        cagr_pct=12.0,
        sharpe=1.5,
        max_drawdown_pct=max_dd,
        trades=12,
        win_rate_pct=58.0,
        benchmark_return_pct=10.0,
        halted=halted,
        equity_curve=pd.DataFrame({"date": [date(2024, 1, 31)], "equity": [final_equity], "n_positions": [0]}),
        trade_log=pd.DataFrame(
            [
                {"entry_date": date(2024, 1, 2), "exit_date": date(2024, 1, 8), "ticker": "NVDA", "pnl_pct": 10.0, "reason": "TAKE"},
                {"entry_date": date(2024, 1, 9), "exit_date": date(2024, 1, 12), "ticker": "AMD", "pnl_pct": -4.0, "reason": "STOP"},
            ]
        ),
    )


def test_build_skills_returns_multiple_research_only_score_styles():
    skills = lab.build_skills(["NVDA", "AMD", "SPY"])

    names = {skill.name for skill in skills}
    assert len(skills) >= 6
    assert "clenow_momentum_90" in names
    assert "breakout_63" in names
    assert "pullback_in_uptrend" in names


def test_skill_score_penalizes_failed_robustness_windows():
    primary = {
        "return_pct": 80.0,
        "sharpe": 2.0,
        "alpha_pct": 25.0,
        "max_drawdown_pct": 7.0,
        "closed_trades": 40,
        "halted": False,
    }
    robustness = [
        {"start": "2021-01-01", "return_pct": -2.0, "alpha_pct": -50.0, "max_drawdown_pct": 22.0, "halted": True},
    ]

    score, penalties, verdict = lab._skill_score(primary, robustness)

    assert score < 80
    assert verdict == "needs_more_evidence"
    assert any("non-positive" in p for p in penalties)
    assert any("halted" in p for p in penalties)


def test_ensemble_candidates_weight_multiple_non_research_skills():
    cards = [
        {
            "skill": "skill_a",
            "paper_skill_score": 90.0,
            "verdict": "paper_candidate",
            "current_top3": ["NVDA", "AMD", "MU"],
        },
        {
            "skill": "skill_b",
            "paper_skill_score": 60.0,
            "verdict": "needs_more_evidence",
            "current_top3": ["AMD", "NVDA", "AVGO"],
        },
        {
            "skill": "skill_c",
            "paper_skill_score": 500.0,
            "verdict": "research_only",
            "current_top3": ["TSLA", "NVDA", "AMD"],
        },
    ]

    rows = lab._ensemble_candidates(cards)

    assert rows[0]["symbol"] == "NVDA"
    assert rows[0]["support_count"] == 2
    assert "skill_a" in rows[0]["supporting_skills"]
    assert "skill_b" in rows[0]["supporting_skills"]
    assert all(row["symbol"] != "TSLA" for row in rows)


def test_run_skill_lab_writes_ranked_research_artifact(monkeypatch, tmp_path):
    skill_a = lab.PaperSkill("skill_a", "trend", "fake A", 10, lambda prices, as_of: pd.Series({"NVDA": 1.0}))
    skill_b = lab.PaperSkill("skill_b", "trend", "fake B", 10, lambda prices, as_of: pd.Series({"AMD": 1.0}))
    calls = {"n": 0}

    def fake_run_backtest(**kwargs):
        calls["n"] += 1
        if calls["n"] <= 6:
            return _fake_result(final_equity=130_000.0, return_pct=30.0, max_dd=5.0)
        return _fake_result(final_equity=110_000.0, return_pct=10.0, max_dd=8.0)

    monkeypatch.setattr(lab, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(lab, "OUT_JSON", tmp_path / "paper-skill-lab-latest.json")
    monkeypatch.setattr(lab, "OUT_MD", tmp_path / "paper-skill-lab-latest.md")
    monkeypatch.setattr(lab, "load_ai_universe", lambda: ["NVDA", "AMD"])
    monkeypatch.setattr(
        lab,
        "price_db_summary",
        lambda: {
            "min_date": date(2020, 1, 1),
            "max_date": date(2024, 1, 31),
            "rows": 10,
            "ticker_count": 3,
            "priced_tickers": {"NVDA", "AMD", "SPY"},
        },
    )
    monkeypatch.setattr(lab, "build_skills", lambda tickers: [skill_a, skill_b])
    monkeypatch.setattr(lab, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(lab, "_current_top_symbols", lambda skill, tickers, end: ["NVDA", "AMD"])

    report = lab.run_skill_lab(write=True)

    assert report["paper_or_live_orders_submitted"] is False
    assert report["skills_evaluated"] == 2
    assert report["ranked_skills"][0]["skill"] in {"skill_a", "skill_b"}
    assert len(report["ensemble_top3"]) >= 2
    assert report["ensemble_candidates"]
    assert (tmp_path / "paper-skill-lab-latest.json").exists()
    assert (tmp_path / "paper-skill-lab-latest.md").exists()


def test_paper_skill_lab_has_no_broker_write_imports():
    src = Path(lab.__file__).read_text()

    forbidden = ["OrderManager", "AlpacaPaperAdapter", "broker_alpaca", ".submit(", "submit_order"]
    assert not any(token in src for token in forbidden)
