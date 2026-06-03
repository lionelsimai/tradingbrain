# TradingBrain Live-Readiness Dossier
_generated 2026-06-02T14:33:37.446456+00:00_

## 1. Executive verdict
- Verdict: LIVE_BLOCKED
- Stress verdict: LIVE_BLOCKED
- Final decision: RESEARCH_ONLY
- Overall score: 0
- Biggest blocker: go_live_blocked

## 2. Current mode
- Mode: paper
- Live trading enabled: False

## 3. Go-live gate table
| Gate | Status | Detail |
|---|---|---|
| 1. Walk-forward OOS | PASS | median OOS Sharpe 0.82 (need >= 0.5); beats SPY in 6/6 windows. WARNING: in-sample beats OOS by 1.69 Sharpe — sizeable, a soft sign of overfitting; have a human review window stability. |
| 2. Monte Carlo worst-case drawdown | NEEDS_HUMAN | Distribution survivable on replay data (99th-pct DD ≈19.1%, ceiling 20.0%), BUT it is resampled from replay (survivorship-biased). Re-run on live fills before trusting. |
| 3. Stress scenarios survived | NEEDS_HUMAN | Worst window: 2020_covid_crash expectancy -0.593R, max consecutive losses 13. Circuit-breaker system wired. Crash windows are negative (expected for trend-following — the edge is being OUT, not long, in crashes). Automated stats cannot certify single-account survival through a compound crash, so this gate needs a human to confirm capital-intact + breakers fired. |
| 4. Overfitting checks | FAIL | IS-vs-OOS Sharpe gap 1.69 exceeds hard limit 1.5 (overfitting risk — OOS must hold up closer to in-sample) |
| 5. Paper matches backtest | FAIL | true live/paper fills: 0 (need >= 50). Replay/backtest evidence is excluded from this gate. Collect real forward paper fills. |
| 6. Risk controls + kill switch + data health | PASS | risk_policy_valid=ok, data_quality_pass=ok, circuit_breakers_present=ok, kill_switch_present=ok |
| 7. Human approval | FAIL | approved is not true; approved_by is empty (need a named human); date is empty; cannot approve a system with no real paper track record (gate 5 not passing); reviewed_pack_sha is empty — set it to the current pack hash (e39e97d34596) to bind approval to the reports you reviewed |

## 4. Evidence source table
| Source | Resolved | Open | Verdict |
|---|---:|---:|---|
| Paper | 0 | 3 | INSUFFICIENT PAPER EVIDENCE (0 paper trades). No paper gating. |
| Live | 0 | 0 | INSUFFICIENT LIVE EVIDENCE (0 live trades). No live gating. |
| Replay | 1919 | 0 | REPLAY-BASED, NOT FORWARD (+0.314R over 1919 replay trades). |

## 5. Paper record summary
- Resolved forward paper trades: 0
- Open forward paper trades: 3
- Replay/backtest evidence is not counted as forward paper evidence.

## 6. Strategy scorecards
- Paper scorecard: INSUFFICIENT PAPER EVIDENCE (0 paper trades). No paper gating.
- Live scorecard: INSUFFICIENT LIVE EVIDENCE (0 live trades). No live gating.
- Replay scorecard: REPLAY-BASED, NOT FORWARD (+0.314R over 1919 replay trades).

## 7. Backtest realism summary
- Gauntlet verdict: REJECTED
- Gauntlet score: 60.5
- Backtest realism stress score: 70

## 8. Monte Carlo summary
- Status: UNKNOWN
- Evidence source: replay
- P99 drawdown: 19.1

## 9. Walk-forward summary
- Status: UNKNOWN
- Verdict: UNKNOWN

## 10. Overfitting summary
- Go-live gate 4 remains the authority for overfitting status.
- 4. Overfitting checks

## 11. Data quality summary
- Pass: True
- Hard failures: 0
- Trust level: UNKNOWN

## 12. Execution stress summary
- Execution score: 100
- Execution cases failed: 0

## 13. Broker chaos summary
- Broker chaos score: 100
- Fake broker chaos uses the order manager path; direct production submits remain forbidden.

## 14. Reconciliation summary
- Reconciliation score: 80

## 15. Incident summary
- Open incidents: 0
- None recorded.

## 16. Kill-switch summary
- Circuit-breaker report: UNKNOWN
- Kill switch is checked by config_guard and risk_gate, and critical incidents engage it.

## 17. Approval summary
- 7. Human approval: FAIL. approved is not true; approved_by is empty (need a named human); date is empty; cannot approve a system with no real paper track record (gate 5 not passing); reviewed_pack_sha is empty — set it to the current pack hash (e39e97d34596) to bind approval to the reports you reviewed

## 18. Observability summary
- Observability score: 60
- Dashboard report: LIVE_BLOCKED

## 19. Dashboard truthfulness check
- Research-only warning: True
- Dashboard must not show live-ready while go-live is blocked.

## 20. Red-team findings
- Red-team report: LIVE_BLOCKED
- Findings: 20
- Blocking findings: 15
- Red-team safety tests are part of the pytest suite.

## 21. Remaining blockers
- go_live_blocked: critical. Clear every go-live gate with real evidence.
- paper_evidence_thin: critical. Collect at least 50 resolved forward paper trades.

## 22. Required next actions
- Safe next action: Run live-like paper mode and collect forward evidence.
- Forbidden next action: Do not enable live trading or bypass gates.

## 23. Final verdict
- Final verdict: LIVE_BLOCKED
- Current mode: paper
- Go-live status: BLOCKED
- This dossier is an evidence pack, not a live-trading approval.
