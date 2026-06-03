from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb

from scripts import forward_paper_evidence as fpe


def _isolate(tmp_path: Path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    kb = tmp_path / "knowledge.duckdb"
    prices = tmp_path / "prices.duckdb"
    monkeypatch.setattr(fpe, "REPORTS", reports)
    monkeypatch.setattr(fpe, "KB", kb)
    monkeypatch.setattr(fpe, "PRICES", prices)
    return reports, kb, prices


def _write_recommendation(reports: Path, *, asof: str = "2026-05-01") -> None:
    (reports / "recommendations.json").write_text(
        json.dumps(
            {
                "asof": asof,
                "regime": {"label": "Bull"},
                "picks": [
                    {
                        "ticker": "MU",
                        "setup": "MOMO_CONT",
                        "direction": "long",
                        "entry_zone": {"low": 100.0, "high": 100.0},
                        "stop_loss": 95.0,
                        "targets": [{"level": 112.0}],
                        "conviction_score": 60,
                    }
                ],
            }
        )
    )


def _write_prices(prices: Path, *, bars: int = 25) -> None:
    con = duckdb.connect(str(prices))
    con.execute(
        """
        CREATE TABLE prices (
            ticker VARCHAR,
            date DATE,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            adj_close DOUBLE,
            volume BIGINT
        )
        """
    )
    start = date(2026, 5, 1)
    for idx in range(bars):
        day = start + timedelta(days=idx)
        mu_close = 100.0 + idx
        spy_close = 500.0 + idx * 0.5
        con.execute(
            "INSERT INTO prices VALUES ('MU', ?, ?, ?, ?, ?, ?, 1000000)",
            [day, mu_close - 0.2, mu_close + 0.5, mu_close - 1.0, mu_close, mu_close],
        )
        con.execute(
            "INSERT INTO prices VALUES ('SPY', ?, ?, ?, ?, ?, ?, 1000000)",
            [day, spy_close - 0.2, spy_close + 0.5, spy_close - 1.0, spy_close, spy_close],
        )
    con.close()


def test_summary_handles_missing_forward_table(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)

    summary = fpe.summarize_forward_evidence(write=False)

    assert summary["available"] is True
    assert summary["total_observations"] == 0
    assert summary["resolved_observations"] == 0
    assert summary["decision_useful"] is False


def test_log_latest_super_smart_is_idempotent_and_research_only(tmp_path, monkeypatch):
    reports, kb, _prices = _isolate(tmp_path, monkeypatch)
    _write_recommendation(reports)

    first = fpe.log_latest_super_smart(top=1)
    second = fpe.log_latest_super_smart(top=1)

    assert first["inserted_observations"] == 3
    assert second["inserted_observations"] == 0
    assert second["duplicate_observations"] == 3
    con = duckdb.connect(str(kb), read_only=True)
    rows = con.execute(
        "SELECT ticker, horizon_days, status, evidence_source FROM forward_paper_observations ORDER BY horizon_days"
    ).fetchall()
    con.close()
    assert rows == [
        ("MU", 1, "pending", "research_forward_observation"),
        ("MU", 5, "pending", "research_forward_observation"),
        ("MU", 20, "pending", "research_forward_observation"),
    ]
    source = Path(fpe.__file__).read_text()
    assert "execution." not in source
    assert "broker_alpaca" not in source


def test_horizon_scorecard_does_not_resolve_without_future_bars(tmp_path, monkeypatch):
    reports, _kb, prices = _isolate(tmp_path, monkeypatch)
    _write_recommendation(reports, asof="2026-05-20")
    _write_prices(prices, bars=1)
    fpe.log_latest_super_smart(top=1)

    card = fpe.write_horizon_scorecard()

    assert card["outcomes_total"] == 0
    assert card["resolution"]["still_pending"] == 3
    assert card["decision_useful"] is False


def test_horizon_scorecard_resolves_1_5_20_day_outcomes(tmp_path, monkeypatch):
    reports, _kb, prices = _isolate(tmp_path, monkeypatch)
    _write_recommendation(reports, asof="2026-05-01")
    _write_prices(prices, bars=25)
    fpe.log_latest_super_smart(top=1)

    card = fpe.write_horizon_scorecard()

    assert card["outcomes_total"] == 3
    assert card["resolution"]["resolved_now"] == 3
    assert {row["horizon_days"]: row["n"] for row in card["by_horizon"]} == {1: 1, 5: 1, 20: 1}
    assert card["by_horizon"][0]["avg_return_R"] == 0.2
    assert card["benchmark_adjusted_evidence_present"] is True
    assert all(row["n"] == 1 for row in card["benchmark_adjusted_by_horizon"])
    assert all(row["n"] == 1 for row in card["slippage_adjusted_by_horizon"])
    assert (reports / "forward-paper-horizon-scorecard-latest.json").exists()
    assert (reports / "forward-paper-horizon-scorecard-latest.md").exists()
