# Scorecard Source Governance

Evidence is SEPARATED by source. Mixing is forbidden for any gating decision.

| File | Source | May drive live gate? | Notes |
|---|---|---|---|
| `reports/scorecard-live.json` | broker-confirmed live fills | YES (needs ≥30) | n=0 today |
| `reports/scorecard-paper.json` | paper fills | NO | forward evidence |
| `reports/scorecard-replay.json` | point-in-time replay of detector | NO (suppress only) | the 1919-trade history |
| `reports/scorecard-backtest.json` | backtest | NO | research only |
| combined view | display only | NO | never read by calibration |

Rules enforced in `scripts/calibration.py` + `tests/test_scorecard_sources.py`:
- `live_gated()` reads ONLY `scorecard-live.json`; returns False with no live fills.
- `replay_negative_gated()` may only SUPPRESS a bleeding setup (conservative), never enable/up-size.
- Unknown setup → probation, size cap 0.25 (policy `scorecard_policy`).
