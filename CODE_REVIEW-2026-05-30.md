# TradingBrain — Code Review & Debug Pass (2026-05-30)

Extensive review of the full codebase (175 Python modules): static analysis
(ruff F/E9), import-graph check, and **runtime edge-case probing** of every
safety-critical path. Below are the real defects found and fixed, and the broad
set of behaviours verified clean.

## Bugs found & fixed

| # | Severity | Bug | Fix |
|---|----------|-----|-----|
| 1 | **High** | **Short selling was not gated.** `risk_gate.check` approved `side="sell"` (opening a short) in a long-only system — a buggy strategy/agent could have opened shorts. | Added `trade_risk.allow_short: false` to the canonical policy; the gate now rejects short opens, rejects invalid sides, and (if ever enabled) enforces short-stop-above-entry. |
| 2 | **High** | **Lifecycle state machine was never wired in.** `execution/order_lifecycle.py` defined valid transitions but `order_manager` never called it — illegal state jumps weren't enforced on the live path. | Wired `order_lifecycle.transition()` into the submit path: proposed→approved→submitted→acknowledged / rejected_by_broker. Illegal jumps now raise. |
| 3 | **Medium** | **State-vocabulary mismatch.** `safety/order.py` used `risk_approved`/`rejected`; the state machine used `approved`/`rejected_pretrade`/`rejected_by_broker`. Divergent vocabularies would desync order state from the machine. | Aligned `order.py` `STATES` to the canonical lifecycle vocabulary (one source of truth). |
| 4 | **Medium** | **Duplicate test silently shadowed.** `test_inv27_zero_size_rejects` was defined twice; Python kept only the second, so one invariant check never ran. | Renamed to `test_inv27b_zero_risk_per_share_rejects`; both now execute. |
| 5 | Low | **Dead code.** Orphaned `swing_low_10` (leftover from the trade_sim refactor) + 19 unused imports / placeholder f-strings across the new packages. | Removed `swing_low_10`; `ruff --fix` cleaned the unused imports. New packages now pass `F811/F821/F841/F706` clean. |

## Verified clean (runtime probes, no defects)

**Risk gate edge cases** — NaN / zero / negative entry rejected; stop-above-entry
(long) rejected; tight-stop position correctly capped at 10% (effective risk
< 1%); confidence floor; reward-to-risk floor; kill switch blocks; paused symbol
blocks; confidence out-of-range handled.

**Portfolio constraints** — max-concurrent, per-position cap, sector cap,
correlated-exposure cap, portfolio heat cap, insufficient cash, duplicate-symbol
(no pyramiding) all block correctly with real price-derived correlations.

**Execution layer** — illegal lifecycle transitions raise; reconciliation detects
ghost positions, quantity mismatches, and stopless positions (incident); paper
adapter rejects oversize (buying-power) orders and fires the stop on a
gap-through bar; order idempotency (same proposal twice → one order); human-review
gating blocks unapproved large/low-confidence orders.

**Governance** — replay scorecard can only suppress, never promote; the live gate
requires live evidence (returns no-gate with zero live fills); event-store
checksum/chain integrity holds after write bursts.

**End-to-end** — `rebuild.py --fast` completes all gating steps (~56s);
`tb analyze` long & short paths render; `paper_trade` fails closed when the market
is closed; `operator status` / `health` green.

## Result

- **171 tests pass** (was 167; +short-selling regression tests, +lifecycle-wiring
  test, +1 previously-shadowed test now running).
- Static safety guard: **PASS**. New packages: **zero** serious lint defects.
- No look-ahead, single order path, fail-closed-live, and replay-never-gates-live
  invariants remain intact after the fixes.

Verdict unchanged: **paper dry-run ready; live disabled by construction.**
