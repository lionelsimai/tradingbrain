# GO-LIVE GATE — Section 14 verdict
_2026-06-03T02:48:34.249131+00:00 · system mode: **read_only**_

## VERDICT: 🔴 **BLOCKED**

Real capital must NOT be risked. Observation/paper mode only until every gate is green.

| # | Gate | Status |
|---|------|--------|
| | 1. Walk-forward OOS | ✅ PASS |
| | 2. Monte Carlo worst-case drawdown | 🟡 NEEDS_HUMAN |
| | 3. Stress scenarios survived | 🟡 NEEDS_HUMAN |
| | 4. Overfitting checks | ❌ FAIL |
| | 5. Paper matches backtest | ❌ FAIL |
| | 6. Risk controls + kill switch + data health | ❌ FAIL |
| | 7. Human approval | ❌ FAIL |

## Detail
- **1. Walk-forward OOS — ✅ PASS**  
  median OOS Sharpe 0.82 (need >= 0.5); beats SPY in 6/6 windows. WARNING: in-sample beats OOS by 1.69 Sharpe — sizeable, a soft sign of overfitting; have a human review window stability.
- **2. Monte Carlo worst-case drawdown — 🟡 NEEDS_HUMAN**  
  Distribution survivable on replay data (99th-pct DD ≈19.1%, ceiling 20.0%), BUT it is resampled from replay (survivorship-biased). Re-run on live fills before trusting.
- **3. Stress scenarios survived — 🟡 NEEDS_HUMAN**  
  Worst window: 2020_covid_crash expectancy -0.593R, max consecutive losses 10. Circuit-breaker system wired. Crash windows are negative (expected for trend-following — the edge is being OUT, not long, in crashes). Automated stats cannot certify single-account survival through a compound crash, so this gate needs a human to confirm capital-intact + breakers fired.
- **4. Overfitting checks — ❌ FAIL**  
  IS-vs-OOS Sharpe gap 1.69 exceeds hard limit 1.5 (overfitting risk — OOS must hold up closer to in-sample)
- **5. Paper matches backtest — ❌ FAIL**  
  live-like paper fills: 0; total paper resolved: 0. Synthetic or non-approved quote-source paper is excluded from this gate. Need >= 50. Replay/backtest evidence is excluded from this gate. Collect real forward paper fills.
- **6. Risk controls + kill switch + data health — ❌ FAIL**  
  risk_policy_valid=ok, data_quality_pass=ok, live_data_health_pass=FAIL, circuit_breakers_present=ok, kill_switch_present=ok
- **7. Human approval — ❌ FAIL**  
  approved is not true; approved_by is empty (need a named human); date is empty; cannot approve a system with no real paper track record (gate 5 not passing); reviewed_pack_sha is empty — set it to the current pack hash (47eec968e3ba) to bind approval to the reports you reviewed

## Hard blockers (must fix)
- 4. Overfitting checks
- 5. Paper matches backtest
- 6. Risk controls + kill switch + data health
- 7. Human approval

## Needs human judgement
- 2. Monte Carlo worst-case drawdown
- 3. Stress scenarios survived

_To grant gate 7: create `config/go_live_signoff.yaml` with `approved: true`, `approved_by:`, `date:` — only after reviewing the pack._