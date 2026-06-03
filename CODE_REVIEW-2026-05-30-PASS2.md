# TradingBrain — Full Code Review & Hardening Pass 2 (2026-05-30)

Scope: entire active codebase after V3 build. I ran the full test suite, static
safety guard, serious lint (`F821/F811/F841/E9/...`), active-module import sweep,
unsafe broker-write grep, dangerous construct scan, end-to-end command smoke
checks, and `rebuild.py --fast`.

## Serious defects found and fixed

| # | Severity | Defect | Fix |
|---|---|---|---|
| 1 | **P0** | `scripts/broker_alpaca.py` still contained a direct `requests.post(.../v2/orders...)` path. It was gated, but it violated the single-order-path invariant. | Rewrote `broker_alpaca.py` as **read-only only**. It can read account/positions and report would-be actions, but cannot submit/cancel/close. Added a forbidden `submit_order()` stub that raises. |
| 2 | **P0 prevention** | Static safety guard only caught shell wrapper writes, not Python direct broker writes. | Strengthened `scripts/ci_static_safety.sh` to fail on Python `requests.post/delete/patch` to Alpaca order/position endpoints outside the explicit disabled stub/tests. |
| 3 | **High** | Duplicate invariant test still existed: `test_inv27_zero_size_rejects` was defined twice; one test was shadowed. | Renamed the second to `test_inv27c_risk_gate_zero_risk_rejects`; both now run. |
| 4 | **Medium** | Dead-code cleanup temporarily removed `ma200` in `scripts/analyze.py`; serious lint caught it (`F821`). | Restored `ma200` calculation and reran tests + command smoke checks. |
| 5 | Low/quality | Remaining active-code dead locals and redefinition warnings (`F841/F811`) in stress test, HMM, sell signals, alpha library, etc. | Removed dead locals/redundant imports. Active code serious lint is clean. |

## Verification performed

- `python3 -m pytest -q` → **172 passed**.
- `bash scripts/ci_static_safety.sh` → **PASS**.
- Serious lint (`F821/F811/F822/F823/F841/E9/...`) on active code → **All checks passed**.
- Active module import sweep → **128 modules imported, 0 failed**.
- Unsafe broker-write scan → no active Python/shell/markdown direct order paths outside the disabled read-only stub/docs/tests.
- Dangerous construct scan (`eval`, `exec`, unsafe yaml, shell=True, os.system) → no active production hits.
- End-to-end commands:
  - `python3 -m scripts.analyze NVDA` OK.
  - `python3 -m scripts.order_dry_run` correctly fails closed when market closed.
  - `python3 -m monitoring.health` OK.
  - `python3 rebuild.py --fast` completed in ~55s; all gating steps passed.
  - Full `compileall` OK.

## Current status

The major vulnerable path I found — the direct Alpaca POST path — is closed. The
system remains intentionally **paper dry-run ready** with live trading disabled by
construction. A future live adapter must be implemented as an `execution.broker_base.BrokerAdapter`
and injected into `execution.order_manager.OrderManager`; no script may call a
broker write endpoint directly.
