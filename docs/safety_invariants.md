# TradingBrain — Formal Safety Invariants

These are properties that must hold at all times. Each is enforced by a test in
`tests/test_safety_invariants.py` and/or `tests/test_red_team_safety.py`. If any
invariant breaks, CI fails and the verdict drops to **Not safe**.

| # | Invariant | Enforced by |
|---|---|---|
| 1 | Only `execution/order_manager.py` submits orders | grep test + adapter guard |
| 2 | Broker adapters never approve trades (no risk logic) | `test_adapter_cannot_approve` |
| 3 | Strategies never size positions directly | `test_strategy_outputs_no_qty` |
| 4 | AI agents never call broker adapters | import-scan test |
| 5 | AI agents never call `order_manager.submit` directly | permission test |
| 6 | Every order proposal passes `risk_gate` | order-path event test |
| 7 | Every order proposal passes `kill_switch.blocked` | `test_kill_switch_blocks` |
| 8 | Every order proposal passes `config_guard.safe_to_trade` | order-path test |
| 9 | Every order proposal passes `quote_validator` | `test_stale_quote_blocks` |
| 10 | Every order proposal passes portfolio constraints | `test_portfolio_*` |
| 11 | Every approved order writes a journal record before submission | event-order test |
| 12 | Every broker response creates an order event | event test |
| 13 | Every fill reconciles against internal state | reconciliation test (P1) |
| 14 | Every rejected proposal saves a reason | `test_rejection_has_reason` |
| 15 | Every scorecard declares `evidence_source` | `test_scorecard_sources` |
| 16 | Replay evidence never controls live gating | `test_replay_not_live_gate` |
| 17 | Paper evidence never controls live gating | `test_paper_not_live_gate` |
| 18 | Combined scorecards are display-only | `test_combined_not_gating` |
| 19 | Unknown setup -> probation/reject (size cap) | `test_unknown_setup_probation` |
| 20 | Unknown data freshness -> reject | `test_unknown_age_rejects` |
| 21 | Unknown broker state -> reject | order-path test |
| 22 | Unknown portfolio state -> reject (fail closed) | order-path test |
| 23 | Unreadable kill switch -> reject | `test_unreadable_kill_switch` |
| 24 | Missing risk policy -> reject (startup fails) | `test_missing_policy_fails` |
| 25 | Conflicting risk policy -> reject (startup fails) | `test_policy_conflict_detected` |
| 26 | Missing stop loss -> reject for long entries | `test_missing_stop_rejects` |
| 27 | Zero/negative position size -> reject | `test_zero_size_rejects` |
| 28 | Duplicate open position -> reject (unless pyramiding) | `test_duplicate_position_rejects` |
| 29 | Duplicate open order -> reject (idempotency) | `test_duplicate_order_rejects` |
| 30 | No production file contains a hardcoded repo path | `test_no_hardcoded_paths` |

## Mode rules (fail-closed)
- `research` / `backtest` / `replay`: order_manager returns `submitted=False` always.
- `paper`: requires policy + kill switch + adapter + journal; orders sized by risk_gate.
- `live`: refused unless `live_trading_enabled=true` (policy) **and** `TB_MODE=live`
  **and** `TB_ALLOW_LIVE=1` **and** `TB_HUMAN_APPROVED=1` **and** reconciliation clear.
  Today the policy ships `live_trading_enabled: false`, so live is **disabled**.

## The one true order path
```
Proposal
  -> config_guard.safe_to_trade   (mode + policy + kill switch readable)
  -> kill_switch.blocked          (halt / pause)
  -> quote_validator.validate     (bid/ask/spread/age/ADV/session, fail-closed)
  -> risk_gate.check              (sizing + exposure + heat + sector + confidence + RR)
  -> human-review gate            (policy thresholds; live always)
  -> idempotency + duplicate-position guard
  -> adapter.submit(OrderIntent)  (the ONLY write; live adapter raises)
  -> event_store events at every step
```
