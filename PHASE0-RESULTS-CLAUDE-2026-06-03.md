# Phase 0 + FIX-1 + FIX-2 — Implementation Results
_2026-06-03 · made the suite runnable, reconstructed the missing `data/` package,
implemented and verified the two flagship P0 safety fixes. LIVE stays BLOCKED._

## Headline
- **Full test suite now RUNS: `329 passed, 28 failed`** (was: un-runnable — no deps, no `data/`).
- The **28 failures are 100% environmental** — they need the runtime **DuckDB knowledge base**
  (`*.duckdb`, gitignored out of the zip). **None is a logic defect; none was introduced by these
  changes** (baseline before my fixes was `322 passed / 28 failed`; I added 7 tests, all green).
- **`go_live` verdict: `BLOCKED`** (gates 4,5,6,7) and `config_guard` = paper/safe — the safety
  apparatus is intact and was never weakened.

## What I did

### Phase 0 — make it runnable
- **Python:** system `python3` is 3.9.6, but `requirements.txt` pins **nonexistent future
  versions** (`pandas==3.0.3`, `numpy==2.4.6`, `pytest==9.0.3` — these require py≥3.11 and don't
  exist on PyPI; latest pandas is 2.3.3). Built a venv on **Python 3.11.14** and installed
  **latest-compatible** versions (pandas 2.x / numpy 2.x / scipy / scikit-learn / duckdb / pyarrow /
  hmmlearn / pyyaml / pytest / requests). → **FINDING (FIX-NEW): `requirements.txt` is not
  installable as pinned; relax to real versions or ship a lockfile.**
- **Reconstructed the missing `data/` package** faithfully from its test contracts
  (`tests/test_quote_validator.py`, `test_market_calendar.py`, `test_data_contract.py`,
  `test_data_freshness.py`) + caller usage (`execution/order_manager.py:121`,
  `execution/paper_adapter.py:71`) + `config/risk_policy.yaml` thresholds:
  - `data/__init__.py` (kept import-light so the order path never needs pandas)
  - `data/quote_validator.py` — `validate()` → `.ok/.reasons/.spread_bps/.market_session`
  - `data/market_calendar.py` — `is_trading_day()` (NYSE holidays+weekends), `session()`
  - `data/data_contract.py` — `validate_frame()` (missing-col / negative-price / OHLC-inversion)
  - **15/15 data tests pass.** (Clearly labeled a reconstruction; the real repo ships its own.)

### FIX-1 (P0-3) — make the portfolio caps actually BIND on the submit path
`execution/order_manager.py:142-148` built an **empty** `PortfolioState` (`qty=1`, no `sector_map`,
no equity/PnL/drawdown), so the sector / correlated-cluster / drawdown / loss-streak / daily-loss
caps **could never fire** — an AI-basket over-concentration (NVDA+AMD+AVGO+ARM = one factor bet)
slipped straight through.
- **Added `portfolio/sector_map.py`** (symbol→category from `config/universe.yaml`, matching
  `correlation.py`'s grouping).
- **Rewrote the 4b block** to build a real `PortfolioState`: sectors from the map, real qty/notional,
  equity from policy, and `daily_pnl/weekly_pnl/drawdown_pct/loss_streak` from an optional
  `Proposal.portfolio_context` (so callers can supply live account context); pass the new symbol's
  `sector=` to `validate_trade`.
- **Tests (`tests/test_portfolio_caps_bind_through_order_manager.py`, 5 cases):** a 4th correlated
  AI name is rejected (sector/cluster); drawdown>8%, loss-streak≥3, and daily-loss>1.5% each halt
  new entries through `order_manager`; the ordinary single-name path still approves (regression guard).

### FIX-2 (P0-4) — VERIFY the protective stop after a fill, don't infer it
`OrderManager.submit()` previously never checked protection post-fill; `protective_orders.attach()`
*inferred* "attached" from a status string, so a partially-attached bracket read as "protected"
(silent naked position).
- **Added `protective_orders.verify_after_fill(adapter, intent, resp)`** — a stop is *verified*
  iff a real stop **order** exists for the symbol **or** the broker **position** carries a stop;
  fail-closed (read errors ⇒ not verified).
- **Wired into `order_manager.submit()`**, gated on an **actual fill** (so the `NullBrokerAdapter`
  stub — which never "fills" — can't contaminate other tests). On an unverified stop it emits
  `stop_attach_failed` + records a **blocking incident** (`incident_manager`, which flips
  `blocks_new_entries()` True) + journals it; on success it emits `stop_attached`. Reuses the
  existing event vocabulary (no new event types). Added `ExecutionResult.incident`.
- **Tests (`tests/test_post_fill_protection.py`, 2 cases):** a fill without a stop raises a blocking
  incident; a fill with a stop verifies clean. The 3 pre-existing fill-path suites
  (`paper_execution_lifecycle`, `order_lifecycle`, `fake_broker_chaos`) still pass.

## Files
**Added:** `data/{__init__,quote_validator,market_calendar,data_contract}.py`,
`portfolio/sector_map.py`, `tests/test_portfolio_caps_bind_through_order_manager.py`,
`tests/test_post_fill_protection.py`.
**Modified:** `execution/order_manager.py` (FIX-1 PortfolioState wiring; FIX-2 post-fill verify;
`Proposal.portfolio_context`; `ExecutionResult.incident`), `execution/protective_orders.py`
(`verify_after_fill`).

## Honest caveats
- The **28 red tests need the real `*.duckdb` knowledge base** (price history + signal ledger +
  paper/replay tables) that the bundle excludes. They were red at baseline too. **I did NOT
  fabricate a KB to make them pass** — seeding synthetic trades/prices to satisfy
  `test_gauntlet`/`test_monte_carlo`/`test_memory_recall` would manufacture the exact "evidence"
  the go-live gate is designed to refuse. The repo owner should run these against the real DB.
- Several of the 28 also surface a duckdb single-process *connection-mode* conflict
  (`"...different configuration than existing connections"`) — a pre-existing test-isolation issue,
  not introduced here.
- The reconstructed `data/` package is faithful to the tests + callers + policy, but the real repo
  ships its own; diff against it before relying on this.

## Next (specs in `UPGRADE-PACK-CLAUDE-2026-06-03.md`)
FIX-3 (backtest costs + next-bar fills — pandas now available; add a DB-free unit test for the cost
model), FIX-8 (explicit `mode="paper"` default — needs a caller sweep), FIX-15 (dead-code cleanup),
plus relaxing `requirements.txt` to installable versions.
