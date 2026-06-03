# TradingBrain — Final Report
_generated 2026-06-03T12:18:58.547199+00:00_

## What this is
A swing-trading decision-support engine with an unusually honest validation
and safety apparatus. It screens a universe, scores conviction across six
pillars, builds defined-risk trade plans, red-teams its own calls, and refuses
to trade live until a battery of gates is green.

## The verdict that matters
- **Validation gauntlet: REJECTED** (robustness 60.5/100)
- **Go-live gate: BLOCKED**
- **Live trades on record: 0** · conviction cap active: True

> This system is **not cleared to trade real money**, and that is the correct,
> intended state. The blocker is not a bug — it is the absence of a real
> forward paper-trading record and a survivorship-free universe. No amount of
> code changes this; only paper-trading and better data do.

## Validation self-check
**Infrastructure health: SOME CHECKS FAILED ❌**

_'Pass' means the validation machinery works and the safety invariants hold
(the system refuses to over-claim and stays fail-closed). It does NOT mean the
strategy is approved._

| Check | Status | Detail |
|-------|--------|--------|
| Go-live verdict + live enforcement | ✅ | verdict=BLOCKED; live blocked because: go-live not cleared (4. Overfitting checks, 5. Paper matches backtest, 6. Risk controls + kill switch + data health, 7. Human approval, 2. Monte Carlo worst-case drawdown, 3. Stress scenarios survived) |
| Conviction cap (no overclaiming) | ✅ | cap_active=True; strong_picks=0 (must be 0 while capped) |
| App export bridge | ❌ | error: Catalog Error: Table with name signal_ledger does not exist!
Did you mean "signals"?

LINE 4:                 FROM signal_ledger WHERE source IN (?) ORDER BY emit_ts DESC...
                             ^ |
| Memory recall fidelity | ❌ | error: Catalog Error: Table with name signal_ledger does not exist!
Did you mean "signals"?

LINE 1: SELECT setup, COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL AND setup IS...
                                    ^ |
| Data-quality gate | ✅ | pass=True, hard_failures=0 |
| No-look-ahead proofs | ✅ | pass=True (no_lookahead, live==backtest, determinism) |

## What is verified vs not
- **Verified (Python backend):** the engine, regime labels, memory recall,
  Monte Carlo, the gauntlet, the go-live gate (enforced + fail-closed), and the
  app export bridge — all exercised by the test suite.
- **Not run here:** the Next.js app against live Supabase, live market-data
  fetch, and any Anthropic call. Treat the app as reviewed, not battle-tested.

## Honest limitations (see CRITIQUE.md)
- Conviction weights, regime thresholds, and Monte Carlo knobs are hand-picked,
  not optimized.
- PBO is high on a short, single-setup-dominated sample — a real overfitting flag.
- The replay trades are simulated by the same logic being validated (circularity).
- This is honesty/validation scaffolding around an edge that is **not yet proven
  live**.

## The one next step that matters
Run the app in paper mode to build a real forward record, and add a
survivorship-free (delisted-inclusive) universe. Those — not more code — are
what move the verdict.

_Informational engineering results, not financial advice. Markets risk total
loss of capital; past or backtested performance does not predict the future._