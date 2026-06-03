# TradingBrain — Execution-Grade Upgrade Pack (Second Pass)
_2026-06-03 · turns the audit into a buildable backlog · LIVE stays BLOCKED_

> **Source:** `AUDIT-CLAUDE-2026-06-03.md` (findings P0-1..P0-5, P1-1..P1-11). This pass does
> **not** re-review. It converts findings into specs an engineer or Claude Code session can build.
>
> **Reuse-first law (read this twice).** TradingBrain already implements ~80% of the "layers"
> Section 5 of the prompt asks for. **Do not build parallel modules.** A second Alpaca client, a
> second risk engine, or a second backtest path would create a second thing to audit and a second
> way to regress safety. **Every item below is MODIFY-existing unless explicitly marked NEW.**
>
> **Two hard preconditions (Phase 0).** Nothing here is testable until: (1) scientific deps are
> installed in a venv (`pandas/numpy/scipy/pytest` are absent), and (2) the `data/` package ships
> (the order path is **not importable** without it; 8 safety tests can't collect). Until Phase 0,
> all "acceptance: tests pass" lines are **unverified by construction** — do not claim otherwise.

---

## A. Execution Summary

This pass produces: a **triage backlog** (B) mapping the 16 findings to fix IDs with owners and
acceptance; a **reuse-first architecture** (C) that points each of the prompt's 12 "brains" at the
file that already implements it and names the *gap*; **five P0 fix specs at function/line level**
(F); a **12-phase roadmap** with per-phase acceptance tests (G); and the targeted upgrades for
strategy/AI-stock/backtest/paper/risk/memory/red-team/dossier/dashboard (H–P). It rejects three
spec items that would *add complexity or risk* (see "Explicitly do NOT build"). One fix is
**implemented now**: the `CLAUDE.md` persona drift (P1-8). The verdict is unchanged and unchangeable
by a plan alone: **`LIVE_BLOCKED`, currently `RESEARCH_ONLY`** — the path to `PAPER_TEST_READY`
runs through Phases 1–7 **plus real forward-paper evidence**, which no code change can manufacture.

**Explicitly do NOT build (skepticism, per Law 5 / "not more complex"):**
- ❌ `alpaca_client/*` (Section 7 group 1) — you have `execution/alpaca_paper_adapter.py` +
  `broker_base.py` with paper-only URL validation, a raising `DisabledLiveAdapter`, and a
  single-writer invariant enforced by `tests/test_red_team_safety.py`. A new client = a second
  write path = the exact regression the CI guard exists to prevent. **Modify the adapter instead.**
- ❌ `risk/risk_brain.py` (Section 7 group 5) — `safety/risk_gate.py` already *is* the Risk Brain
  and is the sole sizer. Renaming/rebuilding risks a fork. **Fill its data gaps (FIX-1).**
- ❌ 18 brand-new schema models (Section 6) — most exist (`RiskDecision`, `OrderIntent`,
  recommender dicts). Typing all 18 is a yak-shave. **Type only the 5 that cross trust boundaries.**

---

## B. Triage Backlog

| ID | Finding (audit) | Pri | Category | File:loc | Failure mode → money/confidence impact | Fix → Test | Effort |
|---|---|---|---|---|---|---|---|
| **FIX-1** | P0-3 caps starved | **P0** | Risk wiring | `execution/order_manager.py:142-148` | Empty `PortfolioState` ⇒ sector/cluster/DD/loss-streak halts **can't fire** on live submit; AI-basket over-concentration slips through ⇒ correlated blow-up | Populate real `PortfolioState` from broker+universe; → `test_portfolio_caps_bind_through_order_manager` | M |
| **FIX-2** | P0-4 stop inferred | **P0** | Execution | `order_manager.py:208-223`, `execution/protective_orders.py:36` | Partially-attached bracket reads "protected" ⇒ **silent naked position**, unbounded downside | Verify stop *order* exists post-fill; incident+block on fail; → `test_post_fill_protection`, `test_stop_verified_not_inferred` | M |
| **FIX-3** | P0-5 costless engine | **P0** | Backtest realism | `backtest/engine.py:8,95,167,219,230` | Zero cost + same-bar-close fill + false "next-day open" docstring ⇒ every headline equity curve / "$ made" **inflated** | NEW `backtest/costs.py`; next-bar fill; gap-fill at gap; → `test_engine_next_bar_and_costs`, `test_gap_through_stop` | M |
| **FIX-4** | P0-2 honest #s ignored | **P0** | Validation gating | `scripts/calibration.py`, `backtest/stress_test.py:198,213`, `scorecards/effective_sample.py` | PBO 92.9% computed then **overridden** by `overfit_flag:false`; eff-N ungated ⇒ overfit setups enabled live | Calibration consumes `gauntlet.json` PBO + eff-N as **hard gates**; → `test_pbo_gates_calibration` | S |
| **FIX-5** | P0-1/P1-6 survivorship edge | **P0** | Data truth | `config/universe.yaml`, `scripts/collective/memory.py:70`, gauntlet/Kelly consumers | Replay edge (+0.314R) drives sizing/break-even/Kelly though it's survivorship+overlap+cost-light ⇒ acting on an artifact | PIT/delisted universe; replay may only *suppress* never size-up; outcome-gate memory; → `test_replay_only_suppresses`, `test_survivorship_degrades_edge` | L |
| FIX-6 | P1-1 `data/` missing | **P1** | Packaging | `paths.py:70`, `order_manager.py:19` | Order path non-importable as shipped; safety tests can't collect | Ship `data/`; → `test_packaging_importable` | S |
| FIX-7 | P1-2 signal fork | **P1** | Strategy | `scripts/signals/swing_setup.py:92` vs `backtest/research_engine.py:114` | "Validated" ≠ "fired" ⇒ gate measures a different signal than trades | Unify or assert divergence; → `test_signal_parity_classify_vs_fires` | M |
| FIX-8 | P1-3 env-inherits live | **P1** | Safety DiD | `order_manager.py:60` | Bare `OrderManager()` under `TB_MODE=live` enters live branch (still blocked downstream) | Explicit `mode="paper"` default arg; → `test_order_manager_mode_none_blocks_live` | S |
| FIX-9 | P1-4 WF overlap | **P1** | Validation | `backtest/walk_forward.py:19,58-62,70` | Overlapping OOS + benchmark-in-universe ⇒ "6/6 beat SPY" overstated | Disjoint folds; exclude SPY/QQQ/SMH; → `test_walk_forward_no_overlap` | M |
| FIX-10 | P1-5 memory inflates | **P1** | Memory | `scripts/collective/memory.py:70-72` | Confidence rises on **repetition** not correctness; no demotion | Outcome-gate + demote-on-contradiction; → `test_repeated_lesson_no_inflation` | M |
| FIX-11 | P1-7 `.env` secrets | **P1** | Hygiene | `.env` | Real paper keys committed; bad precedent | `.env`→`.env.example`; gitignore; CI guard; → `test_env_no_secrets` | S |
| FIX-12 | P1-8 CLAUDE.md drift | **P1** | Agent safety | `CLAUDE.md`, `routines/market-open.md:25` | Tells agent to place orders/trailing stops via refusing wrapper ⇒ conflicting instructions at trade time | Realign to paper-only/order_manager; → `test_routine_doc_no_order_json` | S · **DONE** |
| FIX-13 | P1-9 agent test gap | **P1** | AI safety | `tests/test_agent_permissions.py:18` | Read-only guarantee not scanned over `scripts/agent/` (48KB tool module) | Extend FORBIDDEN_IMPORTS scan; → `test_hermes_tools_no_broker_import` | S |
| FIX-14 | P1-10 cost assumption | **P1** | Backtest | `backtest/trade_sim.py:142` | `risk_frac_of_price=0.06` makes cost 0.03R; halving stop width erases edge | Derive cost from real stop width; gap-fill worse; → `test_cost_uses_real_stop_width` | M |
| FIX-15 | P1-11 dead risk code | **P1** | Correctness | `recommend.py:459`, `risk_gate.py:29`, `risk_policy.yaml` `max_factor_cluster_pct` | Per-setup diversification cap dead; cluster cap declared-not-read; `test_no_hardcoded_risk` near-useless | Wire or delete; strengthen the test; → `test_setup_diversification_cap` | S |
| GAP-16 | Section 9 AI-context | **P2** | Intelligence | `scripts/recommend.py`, `lab/benchmark.py` (not persisted) | No per-trade ticker-vs-{QQQ,SMH,NVDA,basket} or theme warnings in dossier | NEW `research/ai_theme_context.py`; persist `benchmark-*.json`; → `test_ai_trade_has_theme_context` | M |
| GAP-17 | Reconciliation not in loop | **P2** | Execution | `ops/serve.py`, `operator.py:103` | No scheduled broker-vs-internal reconcile in paper loop ⇒ drift uncaught | Wire `execution/reconciliation.py` into serve; → `test_serve_reconciles` | M |

*(P3 items — UI polish, extra strategy families, more charts — deferred; not safety- or evidence-relevant.)*

---

## C. Reuse-First Architecture (12 "brains" → real files)

| # | Brain (prompt §5) | Already implemented at | Status | Gap → action |
|---|---|---|---|---|
| 1 | Data Quality | `data/` (quote_validator, market_calendar), `reports/data-quality.json` | Exists, **missing in bundle** | FIX-6 ship it; add unadjusted-split exclusion (LEU et al.) |
| 2 | Market Regime | `scripts/intelligence/regime_adaptive.py`, `brain/sectors/` | Exists | GAP-16 surface QQQ/SMH/NVDA state into dossier |
| 3 | Feature | `scripts/signals/swing_setup.py:compute_features` (lagged) | **Good** (no-lookahead proven) | none (keep `lab/validate.py` guard) |
| 4 | Strategy | `scripts/signals/`, `scripts/recommend.py`, `strategies/base.py` | Exists | FIX-7 unify classify/fires; type `StrategySignal` |
| 5 | Validation | `backtest/research_engine.py`, `lab/gauntlet.py`, `monte_carlo.py`, `walk_forward.py`, `lab/validate.py` | **Strong tooling** | FIX-4 gate on PBO/eff-N; FIX-9 WF overlap; FIX-3/14 costs |
| 6 | Risk | `safety/risk_gate.py` (sole sizer, fail-closed) | **Strong** | FIX-1 feed it real PortfolioState; FIX-15 dead caps |
| 7 | Paper Execution | `execution/alpaca_paper_adapter.py`, `order_manager.py`, `loops/forward_paper_runner.py` | Strong, paper-only | FIX-2 verify stops; FIX-8 explicit mode |
| 8 | Reconciliation | `execution/reconciliation.py` (solid, **unwired**) | Exists | GAP-17 wire into `ops/serve.py` |
| 9 | Incident | `safety/incident_manager.py`, `kill_switch.py` | Exists, fail-closed | FIX-2 escalate post-fill failures here |
| 10 | Memory | `scripts/collective/memory.py`, `lab/memory_metrics.py` | Honest recall | FIX-10 outcome-gate + demote |
| 11 | Red-Team | `scripts/red_team_live_readiness.py`, `lab/gauntlet.py` | Exists | GAP-16 add per-trade AI challenges |
| 12 | Decision Dossier | `scripts/recommend.py` output, `reports/` | Partial | Add `reasons_to_reject` + ticker-vs-benchmark block |

**Data flow (unchanged, gaps closed):** `data/`✚DQ → regime → features → strategy(one signal) →
`risk_gate`(fed real PortfolioState) → `order_manager`(verify stop post-fill) → paper adapter →
reconcile(wired) → paper scorecard → memory(outcome-gated) → red-team → dossier(reasons-to-reject).

---

## D. Schemas — type only what crosses trust boundaries

Already typed: `RiskDecision` (`safety/risk_gate.py:@dataclass`), `OrderIntent` (`safety/order.py`),
recommender dicts. **Add 5 typed models** (dataclasses, not a new framework):
`StrategySignal` (mandatory `stop_price>0`, `exit_policy`, bounded `confidence`),
`PaperFillRecord` (`fill_price`, `expected_price`, `slippage_bps`, `partial`),
`ReconciliationFinding` (severity enum, `blocks_entries:bool`),
`StrategyScorecard` (the 16 sub-scores → `verdict`, `promotion_allowed`),
`TradeDecisionDossier` (must contain `reasons_to_reject` and `final_verdict != live`).
The other 13 schemas in the prompt → **defer**; they're report shapes already emitted as JSON.

---

## E. Files to CREATE (minimal — 4 source + tests)

1. **`backtest/costs.py`** (NEW) — `CostModel{commission_bps, slippage_bps, spread_bps, half_spread()}`;
   `apply(entry, exit, side, stop_width) -> net_R`. Shared by `engine.py` and `trade_sim.py` (kills the
   `risk_frac_of_price=0.06` magic). Tests: `test_costs_monotonic`, `test_cost_uses_real_stop_width`.
2. **`research/ai_theme_context.py`** (NEW) — `ai_context(ticker, holdings) -> dict` with
   `rs_vs_qqq, rs_vs_smh, rs_vs_nvda, rs_vs_basket, theme_regime, corr_to_holdings, warnings[]`.
   Reject/downgrade when QQQ&SMH both down or ticker lags basket. Test: `test_ai_trade_has_theme_context`.
3. **`reports/benchmark_persist.py`** (NEW, tiny) — run `lab/benchmark.py` and write `reports/benchmark-*.json`
   (it's computed but never saved). Test: `test_benchmark_report_written`.
4. **New test files** (additive, low-risk): the ~17 `test_*` named in B/Q. *Add but mark
   `@pytest.mark.unverified` until Phase 0 lets them run.*

---

## F. Files to MODIFY — the five P0 specs (function-level)

### FIX-1 · `execution/order_manager.py:142-148` — feed Risk Brain real state
```
# BEFORE: PortfolioState(positions=[{symbol, qty:1}], no sector/equity/pnl)
# AFTER: build from broker + universe category map
def _portfolio_state(self, adapter, account, positions) -> PortfolioState:
    cats = load_universe_categories()          # config/universe.yaml -> {sym: sector/theme}
    enriched = [{**p, "sector": cats.get(p["symbol"]), "value": p["qty"]*p["price"],
                 "risk_pct": self._open_risk_pct(p)} for p in positions]
    return PortfolioState(cash=account.cash, equity=account.equity,
        positions=enriched, daily_pnl=self.journal.daily_pnl(),
        weekly_pnl=self.journal.weekly_pnl(), drawdown_pct=self.ledger.drawdown_pct(),
        loss_streak=self.ledger.loss_streak())
```
Then pass it to **both** `risk_gate.check(current_positions=enriched)` and
`portfolio/constraints.evaluate`. **Acceptance:** submitting a 4th semiconductor name with 3 held
breaches `max_sector_pct` / correlated-cluster and is **rejected through order_manager** (today it
isn't). Test: `tests/test_portfolio_caps_bind_through_order_manager.py`.

### FIX-2 · `order_manager.py:208-223` + `execution/protective_orders.py` — verify, don't infer
```
result = adapter.submit(intent)
if result.status == "filled":
    ok = protective_orders.verify_attached(adapter, intent.symbol, intent.quantity)
    #   verify_attached: GET open orders; require a live stop order, qty matches, stop_price set
    if not ok:
        incident_manager.create("missing_protective_stop", severity="blocking",
                                 evidence={"order": result.id})
        adapter.cancel_or_flatten(intent.symbol)   # fail-closed
        return Rejected("post-fill stop not verified at broker")
```
**Acceptance:** `FakeBrokerChaosAdapter` `bracket_partially_attached` ⇒ incident raised + new
entries blocked; **no record ever reads "attached" without a confirmed broker stop order.**
Tests: `test_post_fill_protection`, `test_stop_verified_not_inferred`.

### FIX-3 · `backtest/engine.py` — honest fills + costs (the headline inflation)
- Replace same-bar-close entry (`:219,:230`) with **next-bar open** (or make the assumption explicit
  and identical everywhere); fix the false docstring `:8`.
- Import `backtest/costs.py`; subtract commission+slippage+half-spread on entry **and** exit.
- Gap-through-stop fills at the **bar open when it gaps past the stop**, not at the stop (also patch
  `trade_sim.py:119,123`). **Acceptance:** re-running `scripts/ai_stock_backtest.py` yields
  *lower, cost-bearing* returns; `test_engine_next_bar_and_costs`, `test_gap_through_stop` pass.
  *(Expect the +0.3%-vs-SPY curve to get worse — that's the point.)*

### FIX-4 · `scripts/calibration.py` + `backtest/stress_test.py:198,213` — gate on the honest number
```
pbo = load("reports/gauntlet.json")["portfolio_pbo"]          # 0.929 today
effn = load("reports/backtest-realism.json")["effective_n"]   # << raw_n
for setup in setups:
    setup["overfit_flag"] = setup["overfit_flag"] or pbo > 0.5 or effn < 0.5*raw_n
    setup["enabled"]      = setup["enabled"] and not setup["overfit_flag"]
```
**Acceptance:** with PBO 0.929, **no setup is `enabled:true`**; `test_pbo_gates_calibration`. (This
will correctly *disable the live setups* — the system should not be trading them.)

### FIX-5 · survivorship truth (the largest, highest-value)
- **Universe (`config/universe.yaml` + loader):** add delisted/dead names; mark point-in-time
  membership; backtests must consume membership-as-of-date. Until then, `usable_for: research_only`.
- **Replay may only suppress:** in `scripts/calibration.py`/`gauntlet.py`/Kelly consumers, replay
  expectancy can **reduce** size or **block**, never justify enabling/sizing-up (partly true today —
  make it a tested invariant: `test_replay_only_suppresses`).
- **Memory outcome-gate** (also FIX-10): see N.
- **Acceptance:** `test_survivorship_degrades_edge` — same backtest on a delisted-inclusive universe
  shows materially lower expectancy; readiness stays `RESEARCH_ONLY` until `delisted_rows>0`.

*(P1 modify-specs FIX-6..FIX-15 + GAP-16/17: see B for file:line + test; each is a localized edit.)*

---

## G. Phase Roadmap (acceptance-gated)

- **Phase 0 — Make it runnable.** venv + deps; ship `data/`; `compileall` + `pytest` green; add
  `test_packaging_importable`. *Gate: suite runs at all.* **Everything below is blocked on this.**
- **Phase 1 — Bind the caps (FIX-1).** *Gate: each of sector/cluster/DD/loss-streak rejects through
  `order_manager`.*
- **Phase 2 — Verify protection (FIX-2) + wire reconciliation (GAP-17).** *Gate: partial-bracket ⇒
  incident+block; serve loop reconciles before entries.*
- **Phase 3 — Honest backtest (FIX-3, FIX-14, FIX-9).** *Gate: costs+next-bar+gap fills; WF folds
  disjoint, benchmark excluded; equity curves regenerated lower.*
- **Phase 4 — Gate on honest numbers (FIX-4).** *Gate: PBO>0.5 ⇒ no setup enabled.*
- **Phase 5 — One signal (FIX-7).** *Gate: `classify()`≡`fires()` or asserted divergence.*
- **Phase 6 — Survivorship truth (FIX-5).** *Gate: delisted-inclusive run; edge degrades honestly.*
- **Phase 7 — Forward paper at scale.** Multi-ticker, multi-regime, **≥50 resolved fills**. *Gate:
  `reports/scorecard-paper.json` resolved ≥50.* **(No code can shortcut this.)**
- **Phase 8 — AI-stock context (GAP-16).** *Gate: every AI dossier carries vs-QQQ/SMH/NVDA/basket +
  theme warnings; reject when QQQ&SMH both down.*
- **Phase 9 — Outcome-gated memory (FIX-10).** *Gate: repeating a falsified lesson doesn't raise recall weight.*
- **Phase 10 — Hygiene/DiD (FIX-8, FIX-11, FIX-13, FIX-15).** *Gate: those tests pass.*
- **Phase 11 — Dossier reasons-to-reject + dashboard truth.** *Gate: dashboard never renders costless
  "$ made" or live-ready; `test_dashboard_no_live_ready_badge`.*
- **Phase 12 — Human-review pack** — only after 1–7 + real evidence.

---

## H. Strategy Intelligence Upgrade
Unify the two rule-sets (FIX-7) so the validated signal **is** the traded signal; add a
**parameter-sensitivity gate** (perturb RSI bounds / MA-distance / score coefficients ±15%; if
expectancy flips sign, mark overfit) — the missing guard for 20+ hand-tuned constants. Wire the
declared liquidity floor (`min_avg_dollar_volume`) into candidate generation, not just execution.
Kill the dead per-setup diversification cap (FIX-15) or make it bind.

## I. AI-Stock Intelligence Upgrade (GAP-16)
NEW `research/ai_theme_context.py`: for each AI candidate compute relative strength **vs QQQ, SMH,
NVDA, equal-weight AI basket, and sector peers**; classify AI/semi/mega-cap **theme regime**; compute
**correlation to current holdings** (reuse `portfolio/correlation.py`). Emit warnings: *AI-theme weak,
SMH weak, QQQ weak, NVDA masking weakness, ticker lagging basket, overextended, earnings-gap active,
high-corr-with-holdings, spread-too-wide, narrative-without-data*. **Reject/downgrade** when QQQ&SMH
both trend down, ticker underperforms the basket, or setup is hype-only. Persist `benchmark-*.json`.

## J. Backtest Realism Upgrade (FIX-3/9/14)
Shared `backtest/costs.py`; next-bar fills; gap-through-stop at the gap; cost derived from **real stop
width** not a 0.06 constant; disjoint walk-forward windows with the benchmark **excluded** from the
tradable set; **gate** verdicts on PBO / effective-N / cost-stress (today they're decorative).

## K. Paper Trading Upgrade (FIX-2, GAP-17)
Pre-submit checklist already strong; add **post-fill broker-verified stops**, **scheduled
reconciliation** in `ops/serve.py`, and route all callers (`scripts/paper_trade.py`,
`alpaca_paper_trade_three.py`) through the same post-fill verification the forward-paper runner has.
Keep the paper-only URL validators and single-writer invariant **exactly as-is.**

## L. Risk Control Upgrade (FIX-1, FIX-8, FIX-15)
Feed `risk_gate` + `portfolio/constraints` a **real** PortfolioState so sector/cluster/DD/loss-streak
caps bind; explicit `mode="paper"` default (no env-inherited live); enforce or delete
`max_factor_cluster_pct`; replace the near-useless `test_no_hardcoded_risk` with one that scans for
literal sizing constants outside `config/`.

## M. Memory Learning Upgrade (FIX-10)
`add_lesson` confidence must move on **realized outcome**, not repetition; add
**demotion-on-contradiction** (act on what `lesson_health` already detects); fix the "never
misreports" proof to hold under **mixed replay+live** (filter `truth` by source). Every resolved
paper trade → one `MemoryRecord` with regime/ticker/setup/outcome/evidence.

## N. Red-Team Upgrade (GAP-16)
Extend the existing red-team to challenge **each trade dossier** with the 30 questions (data fresh?
survivorship disclosed? cost-real? beats QQQ/SMH? NVDA-dependent? regime-robust? paper evidence?
reward-risk valid? *is no-trade better?*). **Critical → block paper order; High → human review.**

## O. Dossier Upgrade
`TradeDecisionDossier` must always include **`reasons_to_reject`**, the ticker-vs-benchmark block,
memory recall, red-team findings, and a `final_verdict` that **can never be a live verdict** (assert
in `test_dossier_final_verdict_not_live`).

## P. Dashboard Truthfulness Upgrade
The app must **never** render a "$ made" figure sourced from the costless `engine.py`, nor a
live-ready/green badge from backtest/replay. Tests: `test_dashboard_no_live_ready_badge`,
`test_dashboard_shows_missing_reports`, `test_dashboard_no_costless_dollars`.

## Q. Tests to Add (by group → file)
Map to existing `tests/`: live-block (extend `test_go_live_enforcement`, `test_forbidden_live_weakening`),
data-quality (`test_data_quality_brain`), no-lookahead (extend `test_backtest_realism`), risk
(extend `test_risk_gate` + `test_portfolio_caps_bind_through_order_manager`), realism
(`test_engine_next_bar_and_costs`, `test_gap_through_stop`), validation (`test_walk_forward_no_overlap`,
`test_pbo_gates_calibration`), AI-stock (`test_ai_trade_has_theme_context`), paper
(`test_post_fill_protection`, `test_stop_verified_not_inferred`), reconciliation (`test_serve_reconciles`),
memory (`test_repeated_lesson_no_inflation`), red-team/dossier (`test_dossier_final_verdict_not_live`),
dashboard (`test_dashboard_no_live_ready_badge`), hygiene (`test_env_no_secrets`,
`test_routine_doc_no_order_json`, `test_hermes_tools_no_broker_import`).

## R. Reports to Generate
Add as **gating** inputs: `reports/benchmark-*.json` (persist the computed QQQ/equal-weight),
`reports/pbo.json` + `reports/effective-sample.json` (so go-live can read them directly), and a
**survivorship-/cost-corrected** replay scorecard alongside the current one.

## S. Commands (after Phase 0 only)
```
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
python3 -m compileall -q . && python3 -m pytest -q
python3 -m safety.config_guard && python3 -m lab.go_live --json   # expect BLOCKED
# then per-phase: pytest -q tests/test_portfolio_caps_bind_through_order_manager.py  (Phase 1) ... etc.
```

## T. Remaining Risks (unresolved by this plan)
- **No edge exists to deploy.** Every fix above makes the system *more honest*; none creates alpha.
  After FIX-3/4/5 the measured edge will likely be ~0-to-negative. That is the correct finding.
- **Forward evidence is irreducibly slow** (Phase 7) — gates 5–7 cannot pass without calendar time.
- `data/` contents unverified here (missing from bundle) — DQ/quote-validation claims are trusted, not seen.

---

## U. Final Verdict
```
Final verdict:            LIVE_BLOCKED
Current mode:             paper (default) / research; verdict RESEARCH_ONLY
Live trading:             unreachable without new code; this plan does not change that
Paper trading:            mechanism strong; evidence ~0 (Phase 7 is the long pole)
Backtest intelligence:    world-class tooling, dishonest inputs (FIX-3/4/5/9/14 fix the inputs)
Risk intelligence:        strong gate, starved of data on live path (FIX-1 binds the caps)
AI-stock intelligence:    components exist, not surfaced per-trade (GAP-16)
Memory intelligence:      honest recall, inflates on repetition (FIX-10)
Red-team strength:        present; extend to per-trade dossiers (GAP-16/N)
Dashboard truthfulness:   mostly honest; ban costless "$ made" + live-ready badge (P)
Main strength:            an honesty/safety apparatus that refuses to self-certify
Main blocker:             no demonstrated edge (PBO 92.9%) + caps not binding + no forward evidence
Top 10 upgrades:          FIX-1, FIX-2, FIX-3, FIX-4, FIX-5, FIX-6, GAP-17, FIX-7, FIX-10, GAP-16
Top 10 tests:             portfolio_caps_bind, post_fill_protection, stop_verified, engine_costs,
                          gap_through_stop, pbo_gates_calibration, walk_forward_no_overlap,
                          survivorship_degrades_edge, repeated_lesson_no_inflation, dossier_not_live
Safe next action:         Phase 0 (deps+data+green suite), then Phase 1 (bind the caps)
Forbidden next action:    enabling live, weakening any gate, or treating the replay edge as real
```
_Make it more honest, make the caps bind, stop trusting the survivorship replay, then go earn real
forward-paper evidence. Build through proof. — Second pass, 2026-06-03._
