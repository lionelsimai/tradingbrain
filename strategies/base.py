#!/usr/bin/env python3
"""Strategy contract. A strategy OUTPUTS a SignalCandidate — never an order, never
a broker call, never a final position size. The risk gate sizes; the order manager
places. A strategy missing a stop rule cannot emit a signal.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class SignalCandidate:
    signal_id: str
    timestamp: str
    symbol: str
    direction: str            # long | short
    strategy: str
    setup: str
    confidence: float
    entry_condition: str
    invalidation_condition: str
    stop_loss: float
    take_profit: float | None
    expected_holding_period: int
    evidence_summary: str = ""
    data_snapshot_id: str | None = None
    strategy_version: str = "0"
    feature_version: str = "0"

    def __post_init__(self):
        if self.stop_loss is None or self.stop_loss <= 0:
            raise ValueError("SignalCandidate requires a positive stop_loss")
        if self.direction not in ("long", "short"):
            raise ValueError("direction must be long|short")


@dataclass
class StrategySpec:
    strategy_id: str
    setup_id: str
    universe: str
    timeframe: str
    entry_rule: str
    exit_rule: str
    stop_rule: str
    target_rule: str
    max_hold: int
    valid_regimes: list[str]
    invalid_regimes: list[str]
    data_requirements: list[str]
    feature_requirements: list[str]
    known_failure_modes: list[str]
    benchmark: str
    expected_trade_frequency: str
    min_effective_n_before_promotion: int
    retirement_rule: str


class Strategy(ABC):
    """Concrete strategies subclass this. They can ONLY return SignalCandidates."""
    spec: StrategySpec

    @abstractmethod
    def generate(self, market) -> list[SignalCandidate]:
        ...

    # hard guards — a strategy must never do these
    def submit(self, *a, **k):
        raise PermissionError("strategies cannot submit orders")

    def size(self, *a, **k):
        raise PermissionError("strategies cannot size positions")


if __name__ == "__main__":
    s = SignalCandidate(
        signal_id="s1", timestamp=datetime.now(timezone.utc).isoformat(),
        symbol="NVDA", direction="long", strategy="TREND_LEADER", setup="TREND_LEADER",
        confidence=0.7, entry_condition="close>MA50", invalidation_condition="close<stop",
        stop_loss=206.0, take_profit=236.0, expected_holding_period=10)
    print("valid signal:", s.symbol, s.stop_loss)
    try:
        SignalCandidate(signal_id="s2", timestamp="", symbol="X", direction="long",
                        strategy="Y", setup="Y", confidence=0.5, entry_condition="",
                        invalidation_condition="", stop_loss=0, take_profit=None,
                        expected_holding_period=5)
    except ValueError as e:
        print("rejected no-stop signal:", e)
