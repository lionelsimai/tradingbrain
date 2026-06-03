"""FIX-3 / FIX-14: the shared cost model must express cost from the REAL stop
width (not a fixed fraction), scale monotonically with severity, and fill
gap-through-stop conservatively. Pure unit tests — no price DB required.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import costs


def test_zero_cost_is_zero():
    assert costs.ZERO.cost_in_R(100, 95) == 0.0


def test_round_trip_is_two_sides():
    assert abs(costs.BASE.round_trip_bps() - 2 * costs.BASE.per_side_bps()) < 1e-9


def test_cost_monotonic_in_severity():
    vals = [c.cost_in_R(100.0, 95.0)
            for c in (costs.ZERO, costs.BASE, costs.CONSERVATIVE, costs.SEVERE, costs.CRISIS)]
    assert vals == sorted(vals)
    assert vals[0] == 0.0 and vals[-1] > vals[1] > 0.0


def test_cost_uses_real_stop_width_not_fixed_fraction():
    # The whole point of the fix: a TIGHTER stop (smaller risk/share) costs MORE in R.
    wide = costs.BASE.cost_in_R(entry=100, stop=90)    # 10% stop
    tight = costs.BASE.cost_in_R(entry=100, stop=97)   # 3% stop
    assert tight > wide
    # cost-in-R is inversely proportional to stop width
    assert abs((tight / wide) - (10.0 / 3.0)) < 1e-6


def test_zero_stop_width_is_infinite_cost():
    assert costs.BASE.cost_in_R(100, 100) == float("inf")


def test_gap_through_stop_fills_worse_for_long():
    assert costs.gap_fill_price("buy", stop=95, bar_open=92) == 92   # gap-down: worse
    assert costs.gap_fill_price("buy", stop=95, bar_open=96) == 95   # no gap: at stop


def test_gap_through_stop_fills_worse_for_short():
    assert costs.gap_fill_price("sell", stop=105, bar_open=108) == 108  # gap-up: worse
    assert costs.gap_fill_price("sell", stop=105, bar_open=104) == 105  # no gap: at stop


def test_presets_ordered_and_named():
    assert set(costs.PRESETS) == {"zero", "base", "conservative", "severe", "crisis"}
    e, s = 100.0, 95.0
    assert (costs.PRESETS["base"].cost_in_R(e, s)
            < costs.PRESETS["severe"].cost_in_R(e, s)
            < costs.PRESETS["crisis"].cost_in_R(e, s))
