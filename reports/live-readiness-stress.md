# Live Readiness Stress Report
_Generated 2026-06-02T15:37:26.365532+00:00_

## Executive Verdict
- Verdict: **LIVE_BLOCKED**
- Overall score: 0
- Safety score: 100
- Paper evidence score: 0
- Biggest blocker: go_live_blocked
- Fastest next step: Run live-like paper mode and collect forward paper evidence.

## Evidence Summary
- Missing reports: none
- Paper resolved: 0
- Live resolved: 0
- Replay resolved: 1919

## Stress Results
- commands: pass=3 fail=0 inventory=0
- data: pass=1 fail=0 inventory=18
- signal: pass=2 fail=0 inventory=0
- kill_switch: pass=1 fail=0 inventory=0
- execution: pass=7 fail=0 inventory=0
- approval: pass=6 fail=0 inventory=0

## Blockers
- **go_live_blocked** (critical): Clear every go-live gate with real evidence.
- **paper_evidence_thin** (critical): Collect at least 50 resolved forward paper trades with fresh approved live-like quotes.
- **health_check_failed** (high): Fix failed health components.
- **live_data_health_failed** (high): Start OpenD, refresh moomoo quotes, and re-run live-data health.

## Final Decision
Final verdict: RESEARCH_ONLY
Current mode: paper
Live trading enabled: false
Go-live status: BLOCKED
Paper evidence status: {'paper_resolved': 0, 'paper_live_like_resolved': 0, 'paper_live_like_signals': 0, 'paper_synthetic_quote_signals': 0, 'paper_open': 3, 'live_resolved': 0, 'live_open': 0, 'replay_resolved': 1919, 'paper_verdict': 'INSUFFICIENT PAPER EVIDENCE (0 paper trades). No paper gating.', 'live_verdict': 'INSUFFICIENT LIVE EVIDENCE (0 live trades). No live gating.', 'replay_verdict': 'REPLAY-BASED, NOT FORWARD (+0.314R over 1919 replay trades).'}
Stress status: LIVE_BLOCKED
Critical blockers: 2
High blockers: 2
Open incidents: 0
Safe next action: Run live-like paper mode and collect forward paper evidence.
Forbidden next action: Do not enable live trading or bypass go-live gates.
