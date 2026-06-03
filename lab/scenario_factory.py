#!/usr/bin/env python3
"""Scenario catalog for live-readiness stress tests."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Scenario:
    category: str
    name: str
    expected_behavior: str
    severity: str = "medium"

    def to_dict(self) -> dict:
        return asdict(self)


def data_scenarios() -> list[Scenario]:
    names = [
        "missing_price_bars", "duplicate_price_bars", "out_of_order_bars",
        "split_adjustment_error", "stale_eod_data", "stale_intraday_data",
        "bad_quote", "zero_volume", "negative_price", "extreme_gap",
        "missing_bid", "missing_ask", "bid_higher_than_ask", "spread_too_wide",
        "market_calendar_closed", "timezone_mismatch", "api_timeout",
        "api_rate_limit", "vendor_disagreement",
    ]
    return [Scenario("data", n, "critical invalid data blocks trade; non-critical gaps degrade report", "high")
            for n in names]


def signal_scenarios() -> list[Scenario]:
    names = [
        "no_stop", "poor_reward_risk", "weak_confidence", "stale_quote",
        "wide_spread", "kill_switch_engaged", "daily_loss_cap",
        "weekly_loss_cap", "max_drawdown_cap", "already_holding",
    ]
    return [Scenario("signal", n, "risk gate rejects with a specific reason", "high") for n in names]


def broker_scenarios() -> list[Scenario]:
    from execution.fake_broker_chaos import SCENARIOS
    return [Scenario("execution", n, "no silent failure; incident for unprotected filled risk", "high")
            for n in sorted(SCENARIOS)]


def portfolio_scenarios() -> list[Scenario]:
    names = [
        "max_concurrent_positions", "max_position_size", "max_risk_per_trade",
        "max_portfolio_heat", "max_sector_exposure", "max_correlation_exposure",
        "loss_streak", "pyramiding_attempt", "long_only_violation",
    ]
    return [Scenario("portfolio", n, "trade blocked and journaled", "high") for n in names]


def approval_scenarios() -> list[Scenario]:
    names = [
        "missing_approval", "approval_hash_mismatch", "unnamed_human",
        "approval_before_reports", "approval_with_paper_gate_failing",
        "approval_replay_attack",
    ]
    return [Scenario("approval", n, "go-live remains blocked with exact missing requirement", "critical")
            for n in names]


def ai_scenarios() -> list[Scenario]:
    names = [
        "ai_no_stop", "ai_oversized_trade", "ai_ignores_policy",
        "ai_hallucinates_quote", "ai_requests_live_execution",
        "ai_calls_backtest_live_evidence", "ai_overstates_confidence",
    ]
    return [Scenario("ai", n, "AI output treated as proposal only; risk gate decides", "high")
            for n in names]


def all_scenarios() -> list[Scenario]:
    return (data_scenarios() + signal_scenarios() + broker_scenarios()
            + portfolio_scenarios() + approval_scenarios() + ai_scenarios())


if __name__ == "__main__":
    import json
    print(json.dumps([s.to_dict() for s in all_scenarios()], indent=2))
