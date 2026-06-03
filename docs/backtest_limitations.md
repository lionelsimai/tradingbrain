# Backtest Limitations (read before trusting any number)

The realism manifest (`reports/backtest-realism.json`, `backtest/realism.py`)
declares fidelity honestly:

- **survivorship_bias_free = false** — universe is today's surviving AI names.
- **point_in_time_universe = false** — no historical index membership.
- **total_return / dividend adjusted = false**.
- **delisted_included = false**.
- Costs: commission+slippage+spread modelled in bps; liquidity NOT modelled.
- Benchmarks: SPY, QQQ, equal-weight basket, buy&hold basket (opportunity cost).

**Trust level: INDICATIVE.** Edge per trade dies at ~2x cost assumptions
(`cost_stress`). The portfolio engine underperforms buy-and-hold of the same
names on return; its value is drawdown control. Replay ≠ live; backtest ≠ live edge.
