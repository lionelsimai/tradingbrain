#!/usr/bin/env python3
"""Paper-trading skill lab.

The lab gives TradingBrain more candidate strategy "skills" without giving any
skill permission to trade. It evaluates several AI-stock scoring styles through
the existing historical replay engine, ranks them with drawdown/overfit
penalties, and writes the current top paper candidates for review.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

from backtest.engine import BacktestResult, momentum_score, run_backtest
from paths import REPORTS_DIR
from scripts.ai_stock_backtest import load_ai_universe, price_db_summary


ScoreFn = Callable[[pd.DataFrame, date], pd.Series]
OUT_JSON = REPORTS_DIR / "paper-skill-lab-latest.json"
OUT_MD = REPORTS_DIR / "paper-skill-lab-latest.md"
DEFAULT_INITIAL_EQUITY = 100_000.0

DISCLAIMER = (
    "Research-only skill ranking. Historical replay can overfit and does not "
    "prove future profit. Paper/live orders remain gated separately."
)


@dataclass(frozen=True)
class PaperSkill:
    name: str
    family: str
    description: str
    min_lookback: int
    score_fn: ScoreFn


@dataclass(frozen=True)
class SkillRunConfig:
    start: date
    top_n: int = 3
    rebalance_days: int = 21
    regime_filter: bool = True

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["start"] = self.start.isoformat()
        return out


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        if math.isfinite(out):
            return out
    except Exception:
        pass
    return default


def _restricted(series: pd.Series, allowed: set[str]) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    keep = [ticker for ticker in series.index if str(ticker).upper() in allowed]
    return series.loc[keep].replace([np.inf, -np.inf], np.nan).dropna()


def _price_window(prices: pd.DataFrame, as_of: date, lookback: int) -> pd.DataFrame:
    if as_of not in prices.index:
        return pd.DataFrame()
    idx = list(prices.index)
    i = idx.index(as_of)
    if i < lookback:
        return pd.DataFrame()
    return prices.iloc[i - lookback:i + 1].dropna(axis=1, how="any")


def _return(prices: pd.DataFrame, days: int) -> pd.Series:
    if len(prices) <= days:
        return pd.Series(dtype=float)
    return prices.iloc[-1] / prices.iloc[-days - 1] - 1.0


def _vol(prices: pd.DataFrame, days: int = 63) -> pd.Series:
    returns = prices.pct_change().tail(days)
    return returns.std().replace(0, np.nan)


def _drawdown_from_high(prices: pd.DataFrame, days: int = 63) -> pd.Series:
    window = prices.tail(days)
    highs = window.max()
    return prices.iloc[-1] / highs - 1.0


def build_skills(ai_tickers: list[str]) -> list[PaperSkill]:
    allowed = {ticker.upper() for ticker in ai_tickers}

    def clenow_90(prices: pd.DataFrame, as_of: date) -> pd.Series:
        return _restricted(momentum_score(prices, as_of, lookback=90), allowed)

    def clenow_126(prices: pd.DataFrame, as_of: date) -> pd.Series:
        return _restricted(momentum_score(prices, as_of, lookback=126), allowed)

    def fast_momentum(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 64)
        if w.empty:
            return pd.Series(dtype=float)
        score = 0.65 * _return(w, 21) + 0.35 * _return(w, 63)
        return _restricted(score * 100.0, allowed)

    def multi_horizon_momentum(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 127)
        if w.empty:
            return pd.Series(dtype=float)
        score = 0.50 * _return(w, 63) + 0.30 * _return(w, 126) + 0.20 * _return(w, 21)
        return _restricted(score * 100.0, allowed)

    def low_vol_trend(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 127)
        if w.empty:
            return pd.Series(dtype=float)
        score = (_return(w, 126) + 0.5 * _return(w, 63)) / _vol(w, 63)
        return _restricted(score, allowed)

    def breakout_63(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 84)
        if w.empty or len(w) < 65:
            return pd.Series(dtype=float)
        prior_high = w.iloc[:-1].tail(63).max()
        close = w.iloc[-1]
        score = (close / prior_high - 1.0) * 100.0 + _return(w, 21) * 25.0
        return _restricted(score, allowed)

    def pullback_in_uptrend(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 127)
        if w.empty:
            return pd.Series(dtype=float)
        trend = _return(w, 126)
        pullback = -_drawdown_from_high(w, 21)
        score = trend * 100.0 + pullback.clip(lower=0, upper=0.25) * 80.0
        score = score.where(trend > 0)
        return _restricted(score, allowed)

    def rebound_after_flush(prices: pd.DataFrame, as_of: date) -> pd.Series:
        w = _price_window(prices, as_of, 84)
        if w.empty:
            return pd.Series(dtype=float)
        prior_dd = -_drawdown_from_high(w.iloc[:-1], 63)
        five_day = _return(w, 5)
        score = prior_dd.clip(lower=0, upper=0.4) * 60.0 + five_day * 80.0
        return _restricted(score, allowed)

    return [
        PaperSkill("clenow_momentum_90", "trend", "Annualized log-slope momentum x R2 over 90 trading days.", 90, clenow_90),
        PaperSkill("clenow_momentum_126", "trend", "Slower Clenow-style trend skill over 126 trading days.", 126, clenow_126),
        PaperSkill("fast_21_63_momentum", "momentum", "Fast 21/63-day relative momentum blend.", 64, fast_momentum),
        PaperSkill("multi_horizon_momentum", "momentum", "21/63/126-day momentum blend for persistent AI-stock winners.", 127, multi_horizon_momentum),
        PaperSkill("low_vol_trend", "quality_trend", "Rewards trend persistence while penalizing noisy daily volatility.", 127, low_vol_trend),
        PaperSkill("breakout_63", "breakout", "Scores 63-day highs plus short-term thrust.", 84, breakout_63),
        PaperSkill("pullback_in_uptrend", "pullback", "Looks for dips inside positive 126-day trends.", 127, pullback_in_uptrend),
        PaperSkill("rebound_after_flush", "reversal", "Looks for sharp flushes followed by a 5-day rebound.", 84, rebound_after_flush),
    ]


def _result_metrics(result: BacktestResult, cfg: SkillRunConfig, skill: PaperSkill) -> dict[str, Any]:
    trades = result.trade_log.copy()
    return {
        "skill": skill.name,
        "family": skill.family,
        "start": cfg.start.isoformat(),
        "end": result.end.isoformat(),
        "top_n": cfg.top_n,
        "rebalance_days": cfg.rebalance_days,
        "regime_filter": cfg.regime_filter,
        "final_equity": round(float(result.final_equity), 2),
        "dollars_made_lost": round(float(result.final_equity - result.initial_equity), 2),
        "return_pct": result.return_pct,
        "cagr_pct": result.cagr_pct,
        "sharpe": result.sharpe,
        "max_drawdown_pct": result.max_drawdown_pct,
        "closed_trades": result.trades,
        "win_rate_pct": result.win_rate_pct,
        "benchmark_return_pct": result.benchmark_return_pct,
        "alpha_pct": round(result.return_pct - result.benchmark_return_pct, 2),
        "halted": result.halted,
        "exit_reasons": trades["reason"].value_counts().to_dict() if len(trades) else {},
    }


def _current_top_symbols(skill: PaperSkill, tickers: list[str], end: date) -> list[str]:
    from datetime import timedelta
    from backtest.engine import load_prices

    prices = load_prices(end - timedelta(days=360), end, tickers)
    scores = skill.score_fn(prices, end).dropna().sort_values(ascending=False)
    return [str(x).upper() for x in scores.head(3).index]


def _skill_score(primary: dict[str, Any], robustness: list[dict[str, Any]]) -> tuple[float, list[str], str]:
    notes: list[str] = []
    score = (
        _finite(primary.get("return_pct"))
        + 8.0 * _finite(primary.get("sharpe"))
        + 0.35 * _finite(primary.get("alpha_pct"))
        - 2.2 * _finite(primary.get("max_drawdown_pct"))
    )
    if primary.get("closed_trades", 0) < 30:
        score -= 15
        notes.append("thin primary sample")
    if primary.get("halted"):
        score -= 30
        notes.append("primary run halted")
    for row in robustness:
        if row.get("return_pct", 0) <= 0:
            score -= 20
            notes.append(f"{row.get('start')} non-positive return")
        if row.get("alpha_pct", 0) <= 0:
            score -= 8
            notes.append(f"{row.get('start')} failed benchmark")
        if row.get("max_drawdown_pct", 0) > 18:
            score -= 10
            notes.append(f"{row.get('start')} high drawdown")
        if row.get("halted"):
            score -= 20
            notes.append(f"{row.get('start')} halted")
    verdict = "paper_candidate"
    if primary.get("return_pct", 0) < 25 or primary.get("max_drawdown_pct", 100) > 15:
        verdict = "research_only"
    if any("non-positive" in n or "halted" in n for n in notes):
        verdict = "needs_more_evidence"
    return round(score, 3), notes, verdict


def _ensemble_candidates(skill_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build a consensus symbol list from ranked, non-research-only skills."""
    votes: dict[str, dict[str, Any]] = {}
    for card in skill_cards:
        if card.get("verdict") == "research_only":
            continue
        skill_score = max(_finite(card.get("paper_skill_score")), 0.0)
        if skill_score <= 0:
            continue
        skill_name = str(card.get("skill"))
        for rank, symbol in enumerate(card.get("current_top3") or [], 1):
            ticker = str(symbol).upper().strip()
            if not ticker:
                continue
            weight = skill_score / rank
            row = votes.setdefault(
                ticker,
                {
                    "symbol": ticker,
                    "ensemble_score": 0.0,
                    "supporting_skills": [],
                    "support_count": 0,
                    "best_skill_score": 0.0,
                },
            )
            row["ensemble_score"] += weight
            if skill_name not in row["supporting_skills"]:
                row["supporting_skills"].append(skill_name)
                row["support_count"] += 1
            row["best_skill_score"] = max(row["best_skill_score"], skill_score)
    out = []
    for row in votes.values():
        row["ensemble_score"] = round(float(row["ensemble_score"]), 3)
        row["best_skill_score"] = round(float(row["best_skill_score"]), 3)
        out.append(row)
    out.sort(key=lambda r: (r["ensemble_score"], r["support_count"], r["best_skill_score"]), reverse=True)
    return out


def run_skill_lab(
    *,
    initial_equity: float = DEFAULT_INITIAL_EQUITY,
    write: bool = True,
) -> dict[str, Any]:
    db = price_db_summary()
    ai_tickers = load_ai_universe()
    priced_ai = [ticker for ticker in ai_tickers if ticker in db["priced_tickers"]]
    run_tickers = sorted(set(priced_ai + ["SPY"]))
    skills = build_skills(priced_ai)
    primary_configs = [
        SkillRunConfig(date(2024, 1, 1), 3, 21, True),
        SkillRunConfig(date(2024, 1, 1), 3, 21, False),
        SkillRunConfig(date(2024, 1, 1), 3, 42, True),
        SkillRunConfig(date(2024, 1, 1), 3, 42, False),
    ]
    robustness_configs = [
        SkillRunConfig(date(2021, 1, 1), 3, 21, True),
        SkillRunConfig(date(2025, 1, 1), 3, 21, True),
    ]
    all_runs: list[dict[str, Any]] = []
    skill_cards: list[dict[str, Any]] = []

    for skill in skills:
        primary_rows = []
        for cfg in primary_configs:
            result = run_backtest(
                start=max(cfg.start, db["min_date"]),
                end=db["max_date"],
                score_fn=skill.score_fn,
                top_n=cfg.top_n,
                rebalance_days=cfg.rebalance_days,
                initial_equity=initial_equity,
                benchmark="SPY",
                regime_filter=cfg.regime_filter,
                tickers=run_tickers,
            )
            row = _result_metrics(result, cfg, skill)
            primary_rows.append(row)
            all_runs.append(row)
        primary_rows.sort(key=lambda r: (r["dollars_made_lost"], -r["max_drawdown_pct"]), reverse=True)
        best_primary = primary_rows[0]
        robustness_rows = []
        for cfg in robustness_configs:
            result = run_backtest(
                start=max(cfg.start, db["min_date"]),
                end=db["max_date"],
                score_fn=skill.score_fn,
                top_n=cfg.top_n,
                rebalance_days=best_primary["rebalance_days"],
                initial_equity=initial_equity,
                benchmark="SPY",
                regime_filter=bool(best_primary["regime_filter"]),
                tickers=run_tickers,
            )
            row = _result_metrics(result, cfg, skill)
            robustness_rows.append(row)
            all_runs.append(row)
        score, penalties, verdict = _skill_score(best_primary, robustness_rows)
        skill_cards.append(
            {
                "skill": skill.name,
                "family": skill.family,
                "description": skill.description,
                "paper_skill_score": score,
                "verdict": verdict,
                "penalties": penalties,
                "best_primary_run": best_primary,
                "robustness_runs": robustness_rows,
                "current_top3": _current_top_symbols(skill, run_tickers, db["max_date"]),
            }
        )

    skill_cards.sort(key=lambda r: r["paper_skill_score"], reverse=True)
    ensemble_candidates = _ensemble_candidates(skill_cards)
    report = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "mode": "historical_backtest_replay_only",
        "paper_or_live_orders_submitted": False,
        "account_size_used_for_simulation": initial_equity,
        "latest_local_price_date": db["max_date"].isoformat(),
        "priced_ai_tickers": len(priced_ai),
        "skills_evaluated": len(skills),
        "best_skill": skill_cards[0] if skill_cards else None,
        "ensemble_top3": [row["symbol"] for row in ensemble_candidates[:3]],
        "ensemble_candidates": ensemble_candidates,
        "ranked_skills": skill_cards,
        "all_runs": all_runs,
        "methodology_caveat": DISCLAIMER,
    }
    if write:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        OUT_JSON.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n")
        OUT_MD.write_text(render_markdown(report))
    return report


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# TradingBrain Paper Skill Lab",
        "",
        f"Generated: {report.get('asof')}",
        f"Latest local price date: {report.get('latest_local_price_date')}",
        f"Skills evaluated: {report.get('skills_evaluated')}",
        "",
    ]
    if report.get("ensemble_top3"):
        lines.extend(
            [
                "## Ensemble Candidates",
                "",
                f"Top 3: {', '.join(report.get('ensemble_top3') or [])}",
                "",
            ]
        )
        for row in report.get("ensemble_candidates", [])[:10]:
            lines.append(
                f"- {row.get('symbol')}: score={row.get('ensemble_score')}, "
                f"support={row.get('support_count')}, skills={', '.join(row.get('supporting_skills') or [])}"
            )
        lines.append("")
    lines.append("## Ranked Skills")
    for i, card in enumerate(report.get("ranked_skills", [])[:10], 1):
        b = card.get("best_primary_run") or {}
        lines.append(
            f"{i}. {card.get('skill')} ({card.get('verdict')}) score={card.get('paper_skill_score')} "
            f"made=${b.get('dollars_made_lost'):+,.2f}, return={b.get('return_pct')}%, "
            f"maxDD={b.get('max_drawdown_pct')}%, top3={', '.join(card.get('current_top3') or [])}"
        )
        if card.get("penalties"):
            lines.append(f"   Penalties: {'; '.join(card['penalties'][:4])}")
    lines.extend(["", report.get("methodology_caveat", DISCLAIMER)])
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Evaluate paper-trading strategy skills.")
    ap.add_argument("--equity", type=float, default=DEFAULT_INITIAL_EQUITY)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)
    report = run_skill_lab(initial_equity=args.equity, write=not args.no_write)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        best = report.get("best_skill") or {}
        run = best.get("best_primary_run") or {}
        print(
            f"Best paper skill: {best.get('skill')} made "
            f"${run.get('dollars_made_lost', 0):+,.2f}, "
            f"maxDD={run.get('max_drawdown_pct')}%, current_top3={best.get('current_top3')}"
        )
        print(f"Wrote {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
