"""FIX-1 (P0-3): the sector / correlated-cluster / drawdown / loss-streak / daily-loss
caps must actually BIND on the order_manager submit path.

Before the fix, order_manager built an EMPTY PortfolioState (qty=1, no sector_map,
no equity/PnL/drawdown), so these caps could never fire and an AI-basket
over-concentration (NVDA+AMD+AVGO+ARM = one factor bet) slipped straight through.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om
from safety import kill_switch
from data import market_calendar


def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()


def _prop(**k):
    entry = k.get("entry", 212.65)
    quote = k.pop("quote", dict(bid=entry - 0.05, ask=entry + 0.05, last=entry,
                                ts_age_seconds=2, avg_dollar_volume=5e8, tradable=True))
    base = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
                entry=entry, stop_loss=206.0, take_profit=236.0, confidence=0.7,
                quote=quote, current_positions=[], portfolio_context={})
    base.update(k)
    return om.Proposal(**base)


def test_baseline_single_trade_still_approves(monkeypatch):
    """Regression guard: the fix must not break the ordinary single-name path."""
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = om.OrderManager(mode="paper").submit(_prop(), human_approved=True)
    assert r.approved, r.rejected_reason


def test_sector_or_cluster_cap_binds(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    # three GPU-accelerator names already held (~9% each => ~27% sector)
    held = [{"symbol": "NVDA", "qty": 21, "last": 214.0, "entry": 214.0, "stop": 205.0},
            {"symbol": "AMD",  "qty": 27, "last": 165.0, "entry": 165.0, "stop": 158.0},
            {"symbol": "AVGO", "qty": 9,  "last": 500.0, "entry": 500.0, "stop": 480.0}]
    # a 4th GPU name (ARM) should breach the 30% sector / 35% correlated cap
    r = om.OrderManager(mode="paper").submit(
        _prop(symbol="ARM", entry=140.0, stop_loss=135.0, take_profit=160.0,
              current_positions=held), human_approved=True)
    assert not r.approved, "4th correlated AI name should be rejected"
    reason = (r.rejected_reason or "").lower()
    assert "sector" in reason or "correlated" in reason or "exposure" in reason, reason


def test_drawdown_halt_binds(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = om.OrderManager(mode="paper").submit(
        _prop(portfolio_context={"drawdown_pct": 9.0}), human_approved=True)  # > 8% cap
    assert not r.approved
    assert "drawdown" in (r.rejected_reason or "").lower(), r.rejected_reason


def test_loss_streak_halt_binds(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    r = om.OrderManager(mode="paper").submit(
        _prop(portfolio_context={"loss_streak": 3}), human_approved=True)  # >= 3 cap
    assert not r.approved
    assert "loss streak" in (r.rejected_reason or "").lower(), r.rejected_reason


def test_daily_loss_halt_binds(monkeypatch):
    monkeypatch.setattr(market_calendar, "session", lambda *a, **k: "regular")
    # daily-loss cap 1.5% of $50k = -$750; a -$1000 day must halt new entries
    r = om.OrderManager(mode="paper").submit(
        _prop(portfolio_context={"daily_pnl": -1000.0}), human_approved=True)
    assert not r.approved
    assert "daily loss" in (r.rejected_reason or "").lower(), r.rejected_reason
