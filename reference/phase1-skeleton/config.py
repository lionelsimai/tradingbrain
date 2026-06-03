"""Your guardrails. These are RULES and they are always in charge."""
from dataclasses import dataclass


@dataclass
class Config:
    symbol: str = "DEMO"
    starting_cash: float = 10_000.0
    max_position_pct: float = 0.20        # never put >20% of cash in one trade
    stop_loss_pct: float = 0.05           # bail if a position drops 5%
    take_profit_pct: float = 0.10         # lock in gains at +10%
    max_drawdown_halt_pct: float = 0.15   # KILL SWITCH: no new trades if down 15% from peak
    min_confidence: float = 0.50          # only trade when the brain is confident enough


CFG = Config()
