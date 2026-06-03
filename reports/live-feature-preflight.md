# Live Feature Preflight

- Verdict: LIVE_EXECUTION_LOCKED
- Execution enabled: False
- Paper trading enabled: True
- Go-live status: BLOCKED
- Readiness verdict: RESEARCH_ONLY

## Features
- canonical_risk_policy: READY - risk_policy.yaml is valid
- paper_execution_path: READY - paper mode safe_to_trade passed
- broker_credentials: READY - Alpaca credentials are present and masked
- live_data_health: READY - live data health passed
- go_live_authority: BLOCKED - BLOCKED
- forward_paper_evidence: BLOCKED - 0 resolved forward paper observations
- incident_gate: READY - no blocking incidents open
- dashboard_truthfulness: READY - dashboard shows blocked while authority is blocked

## Live Blockers
- go_live_authority: BLOCKED
- forward_paper_evidence: 0 resolved forward paper observations

Safe next action: Run paper/live-like preflight, collect forward paper evidence, and clear reports before any live review.
Forbidden next action: Do not enable live trading, submit real-money orders, or bypass go-live gates.
