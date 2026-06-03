# The Validation Gauntlet — institutional checks + verdict

This implements the advanced "hostile quant desk" checks the Pro validation spec
demands, the ones that separate a hobby backtest from an institutional one. One
command runs them and returns a 0-100 robustness scorecard with an
APPROVED / CONDITIONAL / REJECTED verdict:
```
python3 -m lab.gauntlet
```

## What it actually tests (all on the real ledger, all labeled honestly)
- **PBO — Probability of Backtest Overfitting.** Cross-validates across the setups
  to estimate how often the "best" setup in-sample is below-average out-of-sample.
- **Deflated Sharpe Ratio.** The Sharpe, penalized for how many variants were tried
  and how short the track record is — the honest significance of the edge.
- **Skill vs market beta.** Regresses returns on the market and compares the win
  rate to a matched-horizon random-entry benchmark. If it can't beat a random long,
  it has no timing skill.
- **Break-even cost.** The cost level at which the edge hits zero, and the headroom.
- **Capacity.** A rough capital ceiling from average dollar volume.
- **Fractional Kelly.** Confirms the risk-per-trade sits safely below the Kelly
  ceiling (over-betting a slightly-wrong edge is the fastest route to ruin).
- **Risk of ruin + losing-streak + recovery** (added to the million-path Monte
  Carlo): the distribution of the worst case, not a single line.

## Today's verdict (honest)
**REJECTED**, overall ~60/100. The reasons it gives are real:
- No forward paper-trading record (Phase K is a required gate) — the decisive one.
- PBO is very high on this data (provisional — only ~8 months of trades and one
  setup dominates, so the cross-validation is noisy, but it is a genuine flag).
- The strategy loses in the worst crash window (trend-following does).
- The in-sample/out-of-sample gap is too large.

What passed: deflated-Sharpe significance, risk of ruin (0%, well under the 1%
tolerance), break-even cost headroom (~10x), and Kelly safety (risk-per-trade is
far below even quarter-Kelly — the correct, conservative choice given the edge is
inflated).

## The honest reading
A couple of headline numbers are artifacts of a short, survivor-only sample (the
"alpha %/yr" is not a real figure — ignore its magnitude; the meaningful read is
the modest +7-point win-rate edge over random entries). The verdict is REJECTED
and will stay that way until the system has a real forward paper record on a fair
universe. This matches the go-live gate. Surviving this gauntlet lowers the chance
of catastrophic failure; it never promises profit.
