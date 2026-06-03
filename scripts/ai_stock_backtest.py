#!/usr/bin/env python3
"""AI-stock historical backtest reporter.

This is a repeatable evidence command for the AI equity universe in
config/universe.yaml. It runs TradingBrain's existing backtest engine against
AI-stock candidates only, includes SPY only as benchmark/regime context, and
writes closed-trade/equity/summary artifacts.

It is intentionally replay-only:
  - no broker imports,
  - no paper/live order submission,
  - every report says historical_backtest_replay_only.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd
import yaml

from backtest.engine import BacktestResult, momentum_score, run_backtest
from paths import CONFIG_DIR, REPORTS_DIR
from scripts.db import PRICES_DB


@dataclass(frozen=True)
class AIStockBacktestConfig:
    name: str
    start: date
    top_n: int = 5
    rebalance_days: int = 21
    regime_filter: bool = True

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["start"] = self.start.isoformat()
        return out


DEFAULT_PRESETS = (
    AIStockBacktestConfig("ai_2024_to_latest_regime_top5_21d", date(2024, 1, 1)),
    AIStockBacktestConfig("ai_2025_to_latest_regime_top5_21d", date(2025, 1, 1)),
    AIStockBacktestConfig("ai_2021_to_latest_regime_top5_21d", date(2021, 1, 1)),
    AIStockBacktestConfig("ai_2024_to_latest_no_regime_top5_21d", date(2024, 1, 1), regime_filter=False),
)


def load_ai_universe(config_path: Path = CONFIG_DIR / "universe.yaml") -> list[str]:
    """Flatten TradingBrain's grouped AI universe while preserving first order."""
    raw = yaml.safe_load(config_path.read_text()) or {}
    tickers: list[str] = []
    for names in (raw.get("universe") or {}).values():
        for ticker in names or []:
            ticker = str(ticker).upper().strip()
            if ticker and ticker not in tickers:
                tickers.append(ticker)
    return tickers


def price_db_summary(prices_db: Path = PRICES_DB) -> dict[str, Any]:
    con = duckdb.connect(str(prices_db), read_only=True)
    try:
        min_date, max_date, rows, tickers = con.execute(
            "SELECT MIN(date), MAX(date), COUNT(*), COUNT(DISTINCT ticker) FROM prices"
        ).fetchone()
        priced = {str(r[0]).upper() for r in con.execute("SELECT DISTINCT ticker FROM prices").fetchall()}
    finally:
        con.close()
    return {
        "min_date": min_date if isinstance(min_date, date) else date.fromisoformat(str(min_date)),
        "max_date": max_date if isinstance(max_date, date) else date.fromisoformat(str(max_date)),
        "rows": int(rows or 0),
        "ticker_count": int(tickers or 0),
        "priced_tickers": priced,
    }


def make_ai_score_fn(ai_tickers: list[str]) -> Callable[[pd.DataFrame, date], pd.Series]:
    """Return a momentum score function restricted to AI-stock candidates."""
    ai_set = {str(t).upper() for t in ai_tickers}

    def score(prices: pd.DataFrame, as_of: date) -> pd.Series:
        scores = momentum_score(prices, as_of)
        keep = [ticker for ticker in scores.index if str(ticker).upper() in ai_set]
        return scores.loc[keep]

    return score


def summarize_result(
    result: BacktestResult,
    cfg: AIStockBacktestConfig,
    *,
    ai_tickers: list[str],
    latest_local_price_date: date,
    equity_path: Path,
    trades_path: Path,
    summary_path: Path,
) -> dict[str, Any]:
    trades = result.trade_log.copy()
    winners = int((trades["pnl_pct"] > 0).sum()) if len(trades) else 0
    losers = int((trades["pnl_pct"] <= 0).sum()) if len(trades) else 0
    avg_trade = float(trades["pnl_pct"].mean()) if len(trades) else None
    median_trade = float(trades["pnl_pct"].median()) if len(trades) else None
    return {
        "name": cfg.name,
        "mode": "historical_backtest_replay_only",
        "not_financial_advice": True,
        "paper_or_live_orders_submitted": False,
        "universe": {
            "configured_ai_tickers": len(ai_tickers),
            "tickers": ai_tickers,
        },
        "params": {
            **cfg.to_dict(),
            "initial_equity": result.initial_equity,
            "end": result.end.isoformat(),
            "benchmark": "SPY",
            "latest_local_price_date": latest_local_price_date.isoformat(),
        },
        "metrics": {
            "final_equity": round(float(result.final_equity), 2),
            "dollars_made_lost": round(float(result.final_equity - result.initial_equity), 2),
            "return_pct": result.return_pct,
            "cagr_pct": result.cagr_pct,
            "sharpe": result.sharpe,
            "max_drawdown_pct": result.max_drawdown_pct,
            "closed_trades": result.trades,
            "winners": winners,
            "losers": losers,
            "win_rate_pct": result.win_rate_pct,
            "avg_closed_trade_pct": round(avg_trade, 3) if avg_trade is not None else None,
            "median_closed_trade_pct": round(median_trade, 3) if median_trade is not None else None,
            "benchmark_return_pct": result.benchmark_return_pct,
            "alpha_pct": round(result.return_pct - result.benchmark_return_pct, 2),
            "halted": result.halted,
            "exit_reasons": trades["reason"].value_counts().to_dict() if len(trades) else {},
            "open_positions_at_end": int(result.equity_curve["n_positions"].iloc[-1])
            if len(result.equity_curve) else 0,
        },
        "artifacts": {
            "equity_csv": str(equity_path),
            "trades_csv": str(trades_path),
            "summary_json": str(summary_path),
        },
        "top_winners": trades.sort_values("pnl_pct", ascending=False).head(8).to_dict("records")
        if len(trades) else [],
        "worst_losers": trades.sort_values("pnl_pct").head(8).to_dict("records")
        if len(trades) else [],
        "last_closed_trades": trades.tail(10).to_dict("records") if len(trades) else [],
    }


def run_ai_stock_backtests(
    configs: tuple[AIStockBacktestConfig, ...] = DEFAULT_PRESETS,
    *,
    initial_equity: float = 100_000.0,
    write: bool = True,
) -> dict[str, Any]:
    ai_tickers = load_ai_universe()
    db = price_db_summary()
    priced_ai = [ticker for ticker in ai_tickers if ticker in db["priced_tickers"]]
    run_tickers = sorted(set(priced_ai + ["SPY"]))
    score_fn = make_ai_score_fn(priced_ai)
    runs: list[dict[str, Any]] = []

    for cfg in configs:
        start = max(cfg.start, db["min_date"])
        result = run_backtest(
            start=start,
            end=db["max_date"],
            score_fn=score_fn,
            top_n=cfg.top_n,
            rebalance_days=cfg.rebalance_days,
            initial_equity=initial_equity,
            benchmark="SPY",
            regime_filter=cfg.regime_filter,
            tickers=run_tickers,
        )
        prefix = f"{cfg.name}-{result.start}-to-{result.end}"
        equity_path = REPORTS_DIR / f"{prefix}-equity.csv"
        trades_path = REPORTS_DIR / f"{prefix}-trades.csv"
        summary_path = REPORTS_DIR / f"{prefix}-summary.json"
        if write:
            REPORTS_DIR.mkdir(parents=True, exist_ok=True)
            result.equity_curve.to_csv(equity_path, index=False)
            result.trade_log.to_csv(trades_path, index=False)
        summary = summarize_result(
            result,
            cfg,
            ai_tickers=priced_ai,
            latest_local_price_date=db["max_date"],
            equity_path=equity_path,
            trades_path=trades_path,
            summary_path=summary_path,
        )
        if write:
            summary_path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        runs.append(summary)

    report = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "mode": "historical_backtest_replay_only",
        "paper_or_live_orders_submitted": False,
        "account_size_used_for_simulation": initial_equity,
        "latest_local_price_date": db["max_date"].isoformat(),
        "price_rows": db["rows"],
        "priced_total_tickers": db["ticker_count"],
        "configured_ai_tickers": len(ai_tickers),
        "priced_ai_tickers": len(priced_ai),
        "missing_price_tickers": [ticker for ticker in ai_tickers if ticker not in db["priced_tickers"]],
        "runs": runs,
    }
    if write:
        out = REPORTS_DIR / f"ai-stock-backtest-summary-{db['max_date']}.json"
        report["artifacts"] = {"combined_summary_json": str(out)}
        out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run AI-stock historical replay backtests.")
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true", help="Run but do not write report artifacts.")
    args = ap.parse_args(argv)
    report = run_ai_stock_backtests(initial_equity=args.equity, write=not args.no_write)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(f"AI-stock replay backtests through {report['latest_local_price_date']}")
        for run in report["runs"]:
            m = run["metrics"]
            print(
                f"  {run['name']}: ${m['dollars_made_lost']:+,.2f} "
                f"({m['return_pct']:+.2f}%), trades={m['closed_trades']}, "
                f"maxDD={m['max_drawdown_pct']}%"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
