"""Paper broker + hard risk rules.  [HOOK 4] swap for a broker's PAPER account."""
from dataclasses import dataclass

from config import CFG


@dataclass
class Portfolio:
    cash: float
    shares: int = 0
    entry_price: float = 0.0

    def value(self, price: float) -> float:
        return self.cash + self.shares * price


def execute(p: Portfolio, d) -> None:
    price = d.price
    if d.action == "BUY" and p.shares == 0:
        qty = int((p.cash * CFG.max_position_pct) // price)
        if qty > 0:
            p.cash -= qty * price
            p.shares = qty
            p.entry_price = price
    elif d.action == "SELL" and p.shares > 0:
        p.cash += p.shares * price
        p.shares = 0
        p.entry_price = 0.0


def risk_check(p: Portfolio, price: float):
    """Hard rules that override the brain: stop-loss and take-profit."""
    if p.shares == 0:
        return None
    change = (price - p.entry_price) / p.entry_price
    if change <= -CFG.stop_loss_pct:
        return "STOP-LOSS hit"
    if change >= CFG.take_profit_pct:
        return "TAKE-PROFIT hit"
    return None
