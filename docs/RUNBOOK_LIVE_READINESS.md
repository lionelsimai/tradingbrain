# Live Readiness Runbook

TradingBrain remains paper-only until every go-live gate passes with real forward evidence and named human approval.

## Kill Switch Engaged
- Symptoms: `safety_state.json` has `halt_all: true`; new entries reject.
- Immediate action: keep entries blocked.
- Commands: `python3 -m safety.kill_switch status`, `python3 -m scripts.operator_status`.
- What not to do: do not release before identifying the trigger.
- Recovery: resolve incident, reconcile positions, run safety tests, then release.

## Filled Position Without Stop
- Symptoms: broker or paper adapter reports a fill with no stop.
- Immediate action: engage kill switch, attach protection manually or close.
- Commands: `python3 -m loops.reconcile`, `python3 -m safety.incident_manager`.
- Escalation: critical incident, human review required.

## Broker Disconnected Or Unknown
- Immediate action: block new entries.
- Check: open orders, fills, positions, cash, protective orders.
- Recovery: reconnect read-only first, reconcile, then resume paper mode only.

## Ghost Or Missing Position
- Immediate action: treat as blocking reconciliation incident.
- Commands: `python3 -m loops.reconcile`, inspect `reports/reconciliation.json`.
- What not to do: do not submit offsetting orders until state is reconciled.

## Data Outage, Stale Quote, Or Wide Spread
- Immediate action: reject trade and record data incident if repeated.
- Commands: `python3 -m monitoring.live_data_health --write-report`, `python3 -m lab.data_quality`.
- Check: `reports/live-data-health.json`, `reports/data-quality.json`, quote age, bid/ask sanity, market calendar.
- Recovery: wait for fresh data or switch to read-only.

## Loss Breach Or Drawdown Breach
- Immediate action: engage kill switch for critical breach.
- Check: risk policy, circuit breaker report, open heat, unresolved positions.
- Recovery: no new entries until human review and risk report are regenerated.

## Paper Scorecard Drift
- Immediate action: demote strategy; do not scale up.
- Check: `reports/scorecard-paper.json` versus backtest/replay.
- Recovery: collect more forward evidence or move strategy to research-only.

## Dashboard Stale
- Immediate action: do not trust UI readiness.
- Commands: `python3 -m monitoring.live_readiness_dashboard`.
- Recovery: regenerate reports and refresh app export.

## Test Suite Failure
- Immediate action: keep live blocked.
- Commands: `python3 -m pytest -q`, targeted failing test.
- Recovery: fix root cause, add regression test, rerun safety subset.

## Go-Live Gate Failure Or Approval Hash Mismatch
- Immediate action: live remains blocked.
- Commands: `python3 -m lab.go_live --json`, `python3 -m lab.go_live --pack-sha`.
- What not to do: do not edit signoff to bypass failed gates.

## Accidental Live Mode Attempt
- Immediate action: verify `TB_ALLOW_LIVE` is unset, engage kill switch if any live path was touched.
- Commands: `python3 -m safety.config_guard`, `python3 -m lab.go_live --json`.
- Recovery: incident review, audit logs, prove no broker live order was submitted.
