from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from backtest.engine import BacktestResult
from scripts import ai_stock_backtest as ab


def test_load_ai_universe_preserves_group_order(tmp_path):
    cfg = tmp_path / "universe.yaml"
    cfg.write_text(
        "universe:\n"
        "  gpu:\n"
        "    - nvda\n"
        "    - AMD\n"
        "  software:\n"
        "    - AMD\n"
        "    - PLTR\n"
    )

    assert ab.load_ai_universe(cfg) == ["NVDA", "AMD", "PLTR"]


def test_make_ai_score_fn_filters_non_ai(monkeypatch):
    monkeypatch.setattr(
        ab,
        "momentum_score",
        lambda prices, as_of: pd.Series({"NVDA": 10.0, "SPY": 9.0, "PLTR": 8.0}),
    )

    out = ab.make_ai_score_fn(["NVDA", "PLTR"])(pd.DataFrame(), date(2026, 1, 2))

    assert list(out.index) == ["NVDA", "PLTR"]
    assert "SPY" not in out.index


def test_summarize_result_reports_dollars_made_lost_and_replay_mode(tmp_path):
    cfg = ab.AIStockBacktestConfig("fixture", date(2024, 1, 1))
    result = BacktestResult(
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        initial_equity=100_000.0,
        final_equity=112_345.67,
        return_pct=12.35,
        cagr_pct=99.0,
        sharpe=1.5,
        max_drawdown_pct=4.2,
        trades=2,
        win_rate_pct=50.0,
        benchmark_return_pct=5.0,
        halted=False,
        equity_curve=pd.DataFrame({"date": [date(2024, 1, 31)], "equity": [112_345.67], "n_positions": [1]}),
        trade_log=pd.DataFrame(
            [
                {"entry_date": date(2024, 1, 2), "exit_date": date(2024, 1, 8), "ticker": "NVDA", "pnl_pct": 10.0, "reason": "TAKE"},
                {"entry_date": date(2024, 1, 9), "exit_date": date(2024, 1, 12), "ticker": "AMD", "pnl_pct": -5.0, "reason": "STOP"},
            ]
        ),
    )

    report = ab.summarize_result(
        result,
        cfg,
        ai_tickers=["NVDA", "AMD"],
        latest_local_price_date=date(2024, 1, 31),
        equity_path=tmp_path / "equity.csv",
        trades_path=tmp_path / "trades.csv",
        summary_path=tmp_path / "summary.json",
    )

    assert report["mode"] == "historical_backtest_replay_only"
    assert report["paper_or_live_orders_submitted"] is False
    assert report["metrics"]["dollars_made_lost"] == 12345.67
    assert report["metrics"]["alpha_pct"] == 7.35
    assert report["metrics"]["winners"] == 1
    assert report["metrics"]["losers"] == 1
    assert report["metrics"]["exit_reasons"] == {"TAKE": 1, "STOP": 1}


def test_ai_stock_backtest_module_has_no_broker_write_imports():
    src = Path(ab.__file__).read_text()

    forbidden = [
        "execution.order_manager",
        "broker_alpaca",
        "AlpacaPaperAdapter",
        ".submit(",
        "submit_order",
    ]
    assert not any(token in src for token in forbidden)


def test_run_ai_stock_backtests_writes_self_describing_artifact(monkeypatch, tmp_path):
    cfg = ab.AIStockBacktestConfig("fixture", date(2024, 1, 1))
    fake_result = BacktestResult(
        start=date(2024, 1, 1),
        end=date(2024, 1, 31),
        initial_equity=100_000.0,
        final_equity=101_000.0,
        return_pct=1.0,
        cagr_pct=12.0,
        sharpe=0.5,
        max_drawdown_pct=1.2,
        trades=0,
        win_rate_pct=0.0,
        benchmark_return_pct=0.2,
        halted=False,
        equity_curve=pd.DataFrame({"date": [date(2024, 1, 31)], "equity": [101_000.0], "n_positions": [0]}),
        trade_log=pd.DataFrame(columns=["pnl_pct", "reason"]),
    )

    monkeypatch.setattr(ab, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(ab, "load_ai_universe", lambda: ["NVDA"])
    monkeypatch.setattr(
        ab,
        "price_db_summary",
        lambda: {
            "min_date": date(2020, 1, 1),
            "max_date": date(2024, 1, 31),
            "rows": 10,
            "ticker_count": 2,
            "priced_tickers": {"NVDA", "SPY"},
        },
    )
    monkeypatch.setattr(ab, "run_backtest", lambda **kwargs: fake_result)

    report = ab.run_ai_stock_backtests((cfg,), write=True)
    out = tmp_path / "ai-stock-backtest-summary-2024-01-31.json"

    assert report["artifacts"]["combined_summary_json"] == str(out)
    assert '"combined_summary_json"' in out.read_text()
