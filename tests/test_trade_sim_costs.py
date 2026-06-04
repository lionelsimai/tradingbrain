"""FIX-14: trade_sim now costs each trade by its REAL stop width, not the flat
risk_frac_of_price=0.06 hack that made tight-stop strategies look far cheaper than
they are. A tighter stop must cost MORE in R."""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import trade_sim, costs


def test_cost_in_R_scales_with_real_stop_width():
    tight = trade_sim.Plan(entry=100.0, stop=99.0, t1=102.0, t2=104.0)   # 1% stop
    wide = trade_sim.Plan(entry=100.0, stop=94.0, t1=106.0, t2=112.0)    # 6% stop
    ct = trade_sim.plan_costs_R(tight, costs.BASE)
    cw = trade_sim.plan_costs_R(wide, costs.BASE)
    assert ct > cw                          # tighter stop => MORE cost in R
    assert ct > 4 * cw                      # ~6x (the flat hack would make them EQUAL)


def test_simulate_applies_real_cost_by_default():
    # a winner that tags t1 then t2; the default (no explicit costs_R) must now
    # subtract the REAL per-plan cost, so it nets less than the costless run.
    fwd = pd.DataFrame({"high": [101.0, 103.0, 105.0],
                        "low": [99.6, 101.0, 103.0],
                        "close": [100.5, 102.0, 104.0]})
    plan = trade_sim.Plan(entry=100.0, stop=99.5, t1=101.0, t2=104.0)
    free = trade_sim.simulate(fwd, plan, costs_R=0.0)   # explicit costless
    real = trade_sim.simulate(fwd, plan)                # FIX-14 default: real cost
    assert real["r"] < free["r"]
