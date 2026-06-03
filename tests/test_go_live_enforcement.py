#!/usr/bin/env python3
"""Guards the audit fix F3: the go-live verdict is ENFORCED in execution, not
advisory. A LIVE order must be rejected while go-live is BLOCKED, and the
rejection must be fail-closed. This test exists so a future refactor cannot
silently drop the enforcement.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om
from safety import kill_switch
from lab import go_live


def setup_function(_): kill_switch.release()
def teardown_function(_): kill_switch.release()


def _prop(**k):
    base = dict(symbol="NVDA", side="buy", strategy="TREND_LEADER", setup="TREND_LEADER",
                entry=212.65, stop_loss=206.0, take_profit=236.0, confidence=0.7,
                quote=dict(bid=212.5, ask=212.8, last=212.65, ts_age_seconds=2,
                           avg_dollar_volume=5e8, tradable=True),
                current_positions=[])
    base.update(k)
    return om.Proposal(**base)


def test_live_order_rejected_while_uncleared():
    """While the system is not cleared, a LIVE order must NOT be approved.
    (Defense in depth: config_guard, go-live, or another gate may catch it —
    the property that matters is that it never gets approved.)"""
    if go_live.gate_reason_for_live() is None:
        return  # genuinely cleared in this environment
    r = om.OrderManager(mode="live").submit(_prop(), human_approved=True)
    assert getattr(r, "approved", None) is not True, \
        "LIVE order was approved while go-live is BLOCKED"


def test_go_live_enforcement_is_wired_into_order_path():
    """Guard against a refactor silently dropping the enforcement: the order
    manager must still consult the go-live verdict for live orders."""
    src = (Path(__file__).resolve().parents[1] / "execution" / "order_manager.py").read_text()
    assert "gate_reason_for_live" in src, \
        "order_manager no longer consults the go-live verdict — F3 has regressed"


def test_enforcement_hook_is_failclosed():
    """The helper must never allow live by accident; with no paper track record
    it must return a blocking reason mentioning the go-live gate."""
    reason = go_live.gate_reason_for_live()
    assert reason is not None and "go-live" in reason.lower()
