# Improvement Backlog
_Generated 2026-06-02T15:11:00.583585+00:00_

- Source verdict: LIVE_BLOCKED
- Items: 4
- Automatic patch candidates: 0
- Manual/evidence items: 4
- Process: Build -> Review -> Test -> Fix specific failures. Use targeted refinement prompts and test-driven gates; avoid open-ended self-refinement.

## Ranked Items
### HB-001 - Clear go-live evidence gates without bypassing safety
- Severity: critical
- Patch class: evidence_gate (manual/evidence)
- Source blocker: `go_live_blocked`
- Safe next action: Resolve each named go-live gate with real artifacts; do not edit signoff until evidence exists.
- Validation: `python3 -m lab.go_live --json`
- Required evidence: reports/go-live.json shows all gates PASS, human signoff bound to current pack hash

### HB-002 - Collect real forward paper evidence
- Severity: critical
- Patch class: evidence_collection (manual/evidence)
- Source blocker: `paper_evidence_thin`
- Safe next action: Run paper mode with live-like quotes until at least 50 resolved forward paper observations exist.
- Validation: `python3 -m loops.forward_paper_runner --once --require-live-data`
- Required evidence: reports/scorecard-paper.json with live_like_resolved_trades >= 50, forward-paper JSONL files with paper-only fills and fresh moomoo decision quotes

### HB-003 - Fix failed operational health components
- Severity: high
- Patch class: observability_or_dependency (manual/evidence)
- Source blocker: `health_check_failed`
- Safe next action: Inspect failed health components and fix the underlying report, data, or service.
- Validation: `python3 -m safety.operator health`
- Required evidence: monitoring health components all ok=true, evidence={'risk_policy': {'ok': True, 'detail': '[]'}, 'kill_switch': {'ok': True, 'detail': 'clear'}, 'db_schema': {'ok': True, 'detail': '[]'}, 'mode': {'ok': True, 'detail': 'paper'}, 'live_data': {'ok': False, 'detail': 'moomoo OpenD is not reachable at 127.0.0.1:11111; reports/moomoo-live-quotes.json is missing; intraday quote age 1551s exceeds 900s freshness limit'}}

### HB-004 - Restore moomoo real-time market-data health
- Severity: high
- Patch class: operational_dependency (manual/evidence)
- Source blocker: `live_data_health_failed`
- Safe next action: Start moomoo OpenD, refresh quotes, and verify reports/live-data-health.json is PASS.
- Validation: `python3 -m monitoring.live_data_health --write-report`
- Required evidence: reports/live-data-health.json ok=true, reports/moomoo-live-quotes.json from moomoo

## Forbidden
- enable live trading
- weaken risk thresholds
- count replay/backtest as paper evidence
- bypass human approval
- ignore failed data health
