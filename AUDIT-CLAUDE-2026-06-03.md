# TradingBrain — Independent Intelligence Audit
_2026-06-03 · evidence-based, static + artifact review · LIVE remains BLOCKED_

> **Method & honesty note.** Scientific deps (`pandas`/`numpy`/`scipy`/`pytest`/`alpaca`)
> are **not installed** in the review environment, so I could **not** run the test
> suite, backtests, or the gauntlet. This audit is therefore: (a) `compileall` (clean,
> exit 0 over core dirs), (b) static reading of the safety/execution/strategy core,
> (c) the on-disk `reports/*.json` artifacts as evidence of what the system itself
> claims, and (d) four parallel subsystem deep-dives. Where I rely on a report the
> system generated, I say so. The `data/` package (`quote_validator`, `market_calendar`)
> is **absent from this bundle**, so the Python order path is not importable as shipped
> and 8 safety tests can't collect — treat that gate as *unverified here*.

---

## A. Executive Summary

TradingBrain is an **unusually disciplined decision-support engine** whose defining
trait is that it **refuses to certify itself**. Its go-live authority is BLOCKED, its
gauntlet is REJECTED (PBO 92.9%), its readiness is RESEARCH_ONLY (6.1/10) — and those
verdicts are **correct**. The safety architecture is genuinely institutional-grade:
live trading is unreachable without writing new code, the AI physically cannot size or
submit an order, and the validation layer is built to disprove its own edge rather than
flatter it.

The flip side: **there is no demonstrated edge.** The headline "+0.314R, PF 2.03"
(`reports/scorecard-replay.json`) is survivorship-biased (80 current AI winners
backfilled), built on overlapping samples (effective-N ≪ raw-N), and cost-light (flips
**negative at 2× costs**, `reports/backtest-realism.json`). The one honest equity curve
on the real universe returns **+0.3% vs SPY +120%** over 2021–2026 — but that engine
applies **zero transaction costs** and fills at the **same bar's close**. And there are
**0 resolved forward-paper trades** (1 ticker, 1 week). So the system is right to stay
blocked, and right to be humble.

### Scores (0–10, evidence-based)

| Dimension | Score | One-line basis |
|---|---:|---|
| **Safety / live-block architecture** | **9** | Live unreachable w/o new code; 4+ independent layers; AI walled off; CI-enforced |
| Risk control (design) | 7 | Excellent fail-closed caps… but several caps are **starved of data** on the live path |
| Execution safety | 7 | Single audited write path; **but** post-fill stop is *inferred not verified*; no live reconciliation |
| AI reasoning | 7 | Structured, evidence-cited, confidence-capped, can't size/submit; enforcement test misses biggest module |
| Memory / learning | 5 | Honest source-separation + decay; **but** confidence inflates on repetition; "never misreports" claim is narrow |
| Backtest realism | 4 | World-class *tooling*; headline engine has **zero costs + same-bar-close fills** |
| Data quality | 4 | Honest manifests, but survivorship-biased, not PIT, not dividend-adj; `data/` pkg missing |
| **Money-making intelligence** | **2** | No demonstrated edge; PBO **92.9%**; honest curve **−120% alpha**; numbers are survivorship artifacts |
| **Paper-trading readiness** | **1** | **0 resolved** forward-paper trades; 1 ticker (MU); 1 week |
| **Live readiness** | **0 (correct)** | Go-live BLOCKED, gauntlet REJECTED — and that is the right state |
| **Overall** | **~5** | Top-tier safety/honesty engineering around an unproven (currently negative-after-cost) edge |

**Final verdict: `LIVE_BLOCKED`** — and the system already enforces this itself. The work
ahead is not "go live"; it's **earn the right to paper-test for real**, then collect honest
forward evidence, then let the gates decide.

---

## B. What TradingBrain Already Does Well

1. **The live-block is real and layered** (`execution/alpaca_paper_adapter.py:21,51-55,79-80`;
   `execution/broker_base.py:51-53,117-134`; `safety/config_guard.py:114-122`;
   `execution/order_manager.py:104-112`; `ops/serve.py:72-75`). The live host
   `api.alpaca.markets` appears **only in tests that assert it is refused**. To reach live
   you'd have to flip `risk_policy.yaml`, set 3 env flags, sign off a SHA-bound approval,
   **and write a new adapter** — there is no single switch.
2. **AI cannot trade or size.** `agents/permissions.py:21-31` forbids `submit_order`/
   `size_position`/broker imports; `BaseAgent` raises `PermissionError`; `Proposal` has no
   size field; sizing is computed **only** in `risk_gate.py:166-169` and is **decoupled from
   confidence**. Verified by `tests/test_red_team_safety.py:40-48` (only `order_manager.py`
   may call `adapter.submit`).
3. **The validation layer tries to *disprove* the edge.** `lab/validate.py:50` corrupts all
   future bars and asserts byte-identical decisions (look-ahead proof, PASS). `lab/stats.py`
   has genuine CSCV/PBO, Deflated Sharpe (Bailey–López de Prado), and stationary bootstrap
   (Politis–Romano). `backtest/monte_carlo.py:82-95` uses block bootstrap that **preserves
   losing streaks** and warns that IID understates drawdown.
4. **The go-live gate is excellent.** `lab/go_live.py` defaults BLOCKED, fails closed,
   reads real artifacts, **excludes replay/synthetic from the paper gate** (gate 5), makes
   the IS-vs-OOS Sharpe gap a **hard fail** (gate 4; 1.69 > 1.5 → FAIL), and binds human
   approval to a **SHA of the exact reports reviewed** (gate 7) so stale approvals void.
5. **Pervasive, enforced honesty.** Conviction capped at "moderate" until live fills exist
   (`scripts/recommend.py:414`); replay scorecards labeled "INDICATIVE — survivorship-biased";
   replay can only *suppress*, never *promote* (`scripts/calibration.py:123-138`); memory
   labels replay vs live and age-decays lessons (`scripts/collective/memory.py:125-255`).
6. **One audited write path** (`execution/order_manager.py:67-233`) with deep pre-trade
   gating, deterministic idempotency keys (`safety/order.py:27-42`), three-layer
   duplicate/pyramiding protection (fail-closed on broker-read error), and full event
   journaling. The agent shell wrapper is **read-only** (`scripts/wrappers/alpaca.sh:23-26`),
   the old write wrapper is **quarantined** (`deprecated/unsafe_wrappers/alpaca.sh`), and a CI
   static check (`scripts/ci_static_safety.sh`) blocks regressions.

---

## C. Critical Weaknesses (P0)

> None of these are "the live block leaks." They are: (i) the edge is unproven/negative
> after honest costs, and (ii) several advertised risk caps don't actually bind on the real
> order path.

- **P0-1 · No demonstrated edge; the headline number is an artifact.**
  `reports/scorecard-replay.json` (+0.314R, 1919 trades) is consumed by memory, calibration,
  gauntlet break-even and Kelly — but it is survivorship-biased (universe = today's AI
  winners, `config/universe.yaml`, `survivorship_bias_free: false`), overlapping
  (`scorecards/effective_sample.py`: raw 800 → eff 300; "top 1% drive 83.7% of expectancy"),
  and cost-light (**2× cost → −0.0283R**, `reports/backtest-realism.json`). The honest engine
  on the same names returns **+0.3% vs SPY +120%**. *The system's own gauntlet PBO of 92.9%
  says "selection worse than random."*

- **P0-2 · The damning numbers are computed and then NOT acted on.**
  `lab/gauntlet.py:84` computes **PBO 92.9% (FAIL)**, yet `reports/calibration.json` marks
  **every setup `overfit_flag:false`, `enabled:true`** via a weaker per-setup heuristic
  (`backtest/stress_test.py:198,213`). The *operational* path follows the flattering flag.
  Effective-N and concentration warnings are displayed but **gate nothing**.

- **P0-3 · Concentration & drawdown caps are starved of data on the live path.**
  `execution/order_manager.py:142-148` builds `PortfolioState` with **no `sector_map`, no
  per-position sector, `qty=1` hardcoded, and no equity/PnL/drawdown/loss-streak**. So
  `portfolio/constraints.evaluate`'s sector cap, correlated-cluster cap, and the
  daily/weekly/drawdown/loss-streak halts **cannot fire** through the real submit path. The
  "six AI names = one factor bet" logic (`portfolio/correlation.py`) exists but is **not fed
  live data** — NVDA+AMD+AVGO would not be recognized as one cluster at submit time.

- **P0-4 · Post-fill stop is *inferred*, never *verified*.**
  `OrderManager.submit` (`execution/order_manager.py:223`) checks only that status isn't
  rejected — it never confirms a protective stop **order** exists at the broker, never handles
  partial fills, never escalates an incident. `protective_orders.attach` and
  `forward_paper_runner.py:454` infer "attached" from a **status string**. A partially-attached
  Alpaca bracket (a real failure mode) reads as "protected" → **silent unbounded downside** on
  a real position. Post-fill safety exists *only* in `loops/forward_paper_runner.py:500-512`;
  other callers (`scripts/alpaca_paper_trade_three.py`, `scripts/paper_trade.py`) get a fill
  with no stop confirmation.

- **P0-5 · The headline backtest engine has zero costs and same-bar-close fills.**
  `backtest/engine.py` models **no** commission/slippage/spread/liquidity, fills entries at
  **that day's close** (`:219,:230`) while scoring on a window that **includes that close**
  (`:95,:188`) — and its docstring **falsely claims "next-day open"** (`:8`). Every
  `ai-stock-backtest` equity curve and any dashboard "dollars made" inherits this inflation.

---

## D. High-Risk Weaknesses (P1)

- **P1-1 · `data/` package missing from the bundle** (`execution/order_manager.py:19`,
  `paths.py:70`). Order path non-importable as shipped; safety tests can't collect. Confirm
  whether this is a packaging slip or real — it determines whether the safety net is even
  exercisable.
- **P1-2 · Two non-identical signal rule-sets.** Live `swing_setup.classify()` (e.g. PULLBACK
  `25≤RSI≤40`, `<5%` to MA50) vs research `research_engine.fires()` (`25≤RSI≤45`, `<4%`). The
  Deploy/Iterate/Reject verdict that gates live size is measured on a **different signal than
  trades**.
- **P1-3 · `OrderManager(mode=None)` inherits `TB_MODE` from env** (`order_manager.py:60`).
  A bare manager under `TB_MODE=live` enters the live branch (still blocked downstream, but
  it erodes defense-in-depth). Prefer an explicit default-paper argument.
- **P1-4 · Walk-forward folds overlap and include the benchmark in the universe**
  (`backtest/walk_forward.py:58-62,19-22,70`). "6/6 windows beat SPY" is **not 6 independent
  tests**, and SPY/QQQ/SMH are tradable within the same frame.
- **P1-5 · Memory confidence inflates on repetition without outcome gating**
  (`scripts/collective/memory.py:70-72`): `add_lesson` adds +0.05 per duplicate string, capped
  0.99 — confidence tracks *how often a string was re-asserted*, not whether it was right.
  No demotion-on-contradiction path.
- **P1-6 · The "memory never misreports" proof is narrow/near-vacuous.**
  `lab/memory_metrics.py:181-196` compares the largest single-source group to a **source-blended**
  truth; it only equals 100% when every setup is single-source (true today because live_n≈0).
  Under mixed replay+live it would drop. The README claim oversells it.
- **P1-7 · `.env` commits real (paper) Alpaca + Finnhub keys.** Paper-only, but live creds in a
  tracked file is poor hygiene and a bad precedent.
- **P1-8 · CLAUDE.md / routines are stale and self-contradictory.** They tell the agent to place
  orders / a "10% trailing GTC stop" via the wrapper that now **refuses** (`CLAUDE.md:30,40`;
  `routines/market-open.md:25` embeds raw order JSON). The trailing-stop strategy rule has **no
  implementation** in the safe path. An autonomous agent gets conflicting instructions at the
  exact moment it would trade.
- **P1-9 · Agent read-only guarantee is under-tested.** `tests/test_agent_permissions.py:18-22`
  scans only `agents/*.py` (trivial dataclasses); it does **not** scan the real LLM tool layer
  `scripts/agent/hermes_tools.py` (48KB) or `scripts/collective/`. The guarantee is design-correct
  but asserted-by-docstring where it matters most.
- **P1-10 · Cost model assumption is load-bearing and optimistic.** `backtest/trade_sim.py:142`
  divides bps by an assumed `risk_frac_of_price=0.06`; halving the assumed stop width doubles
  cost and erases the edge. Gap-through-stop fills **at the stop, never worse** (`:119,:123`),
  understating exactly the overnight-gap tail (worst-decile −1.71R) that dominates this strategy.
- **P1-11 · Dead/misleading risk code.** Per-setup diversification cap is dead
  (`scripts/recommend.py:459`, `seen_setup` never read); `max_factor_cluster_pct: 40` declared,
  read nowhere; `HUMAN_REVIEW_*` constants in `risk_gate.py:29-30` unused;
  `tests/test_no_hardcoded_risk.py:6-9` only bans two literal patterns — false coverage.

---

## E. Missing Brain Components (for *smarter* intelligence)

1. **A point-in-time, delisted-inclusive universe** — the single highest-value upgrade; without
   it every edge number is an optimistic ceiling.
2. **A cost/capacity-realistic execution simulator** wired into the *headline* engine (slippage,
   commission, spread, ADV cap, partial fills, gap-through-stop *at the gap*).
3. **A gating layer that consumes the honest numbers** — PBO, effective-N, concentration, and
   cost-stress must be able to **downgrade a verdict**, not just print.
4. **A single canonical signal definition** shared by live + research (kill the `classify()`/
   `fires()` fork).
5. **A "no-trade / hold-cash" decision** as a first-class output ranked against benchmark
   alternatives (QQQ/SMH/cash), so the brain can choose *not* to be long.
6. **Forward-paper evidence at scale** — the only thing that can move gates 5–7.
7. **Post-fill protection verification + scheduled broker reconciliation** in the live loop.
8. **Outcome-gated memory** — confidence that moves on *being right*, with demotion on contradiction.

---

## F. Codebase Map (buckets)

| Bucket | Paths | Quality | Top weakness |
|---|---|---|---|
| Safety / gates | `safety/` (config_guard, risk_gate, risk_policy, kill_switch, incident_manager, go_live via `lab/`) | **Excellent** | Caps starved of data on live path (P0-3) |
| Execution / broker | `execution/` (order_manager, alpaca_paper_adapter, broker_base, protective_orders, reconciliation) | Strong | Post-fill stop inferred, no live reconcile (P0-4) |
| Strategy / signals | `scripts/signals/`, `scripts/recommend.py`, `scripts/alphas/`, `brain/` | Sophisticated | 20+ hand-tuned constants; `classify()`≠`fires()` |
| Backtest / validation | `backtest/`, `lab/`, `_clenow_lab/`, `scorecards/` | World-class tooling, poisoned inputs | Costless close-fill engine (P0-5); PBO ignored (P0-2) |
| Data pipeline | `data/` (**missing in bundle**), `config/*.yaml` | Unverifiable here | Survivorship/not-PIT; pkg absent (P1-1) |
| Portfolio | `portfolio/` (constraints, correlation, portfolio_state, exposure) | Best-designed risk logic | Not fed live data (P0-3) |
| AI agents | `agents/`, `scripts/agent/`, `scripts/agents/`, `scripts/collective/`, `prompts/` | Well-fenced | Enforcement test misses biggest module (P1-9) |
| Memory / journal | `memory/`, `scripts/collective/memory.py`, `journal/` | Honest, decayed | Confidence inflates on repetition (P1-5) |
| Reports / dashboards | `reports/`, `app/` (Next.js), `scorecards/` | Truthful artifacts | Headline $ from costless engine (P0-5) |
| Ops / loops / routines | `ops/serve.py`, `loops/`, `routines/`, `.github/` | Solid serve guard | Stale/contradictory routines (P1-8) |
| Tests | `tests/` (~30 safety-focused) | Strong breadth | Gaps: post-fill, PortfolioState, agent-tool scan |
| Docs | 182 `.md` (DOCTRINE, GAUNTLET, RIGOR, AUDIT-*, this) | Exceptional self-criticism | CLAUDE.md drift (P1-8) |

---

## G. Trading-Logic Review

6-pattern swing detector (`scripts/signals/swing_setup.py`) → six-pillar conviction scorer
(`scripts/recommend.py`) → adaptive overlay that can only *reduce* size
(`scripts/intelligence/`). **Strengths:** production path has **no same-bar leakage** (signal
on bar `i`'s close, sim on `i+1:`); a strategy is *physically unable* to size/submit
(`strategies/base.py:69-73` raises `PermissionError`); a signal can't exist without a positive
stop. **Weaknesses:** every pattern is a stack of hand-set thresholds + a hand-set scoring
polynomial (e.g. `0.70+(40−RSI)/100`) — 20+ free params, **no parameter-sensitivity test gates
deployment**; `TREND_LEADER` is an admitted "always have a buy" fallback (`swing_setup.py:121-129`)
that biases the system to always be long high-beta AI names; detector targets (e.g.
MEAN_REVERSION → MA20) differ from the simulated targets, so the **R:R a user sees isn't the one
validated**; the liquidity floor (`min_avg_dollar_volume`) is declared but **not applied** in
candidate generation. `EARNINGS_DRIFT` is listed but unimplemented.

## H. Backtest Review

Two engines that disagree. **Engine A** (`backtest/engine.py`, the one whose equity curves are on
disk): zero costs, same-bar-close fill, mislabeled docstring → headline inflation (P0-5).
**Engine B** (`trade_sim`/`stress_test`/`research_engine`): correct next-bar fills + costs, but
costs are tuned negligible (P1-10), gap-through-stop is optimistic, and it runs on the
survivorship universe. The **rigor library is genuinely excellent** (PBO/DSR/stationary
bootstrap, look-ahead corruption proof) — but the inputs are poisoned and the worst readouts
(PBO 92.9%, effective-N) **gate nothing** (P0-2). Walk-forward folds overlap and include the
benchmark (P1-4). Net: **no edge is demonstrated; the after-honest-cost edge is ~zero-to-negative.**

## I. Alpaca / Execution Review

**Live-block: strong, layered, CI-enforced** (Section B). Single audited write path with
idempotency, three-layer duplicate/pyramiding protection (fail-closed on broker-read error),
chaos-tested (`execution/fake_broker_chaos.py`, 30+ failure modes). **Gaps:** post-fill stop
inferred not verified (P0-4); no broker-vs-internal reconciliation wired into `ops/serve.py`
(`operator.py:103-106` reconciles empty lists); `OrderManager(mode=None)` env-inherits live
(P1-3); secrets in `.env` (P1-7).

## J. Paper-Trading Review

The mechanism exists (`loops/forward_paper_runner.py`) and is the *only* caller with post-fill
incident logic. But the **evidence is essentially nil**: `reports/forward-paper/` shows **0
resolved, 3 pending, 1 ticker (MU), 1 week** (`reports/forward-paper-evidence.json`). Gate 5
correctly refuses to be satisfied by replay. **Until real forward fills accumulate (need ≥50,
multi-ticker, multi-regime), nothing else matters for live readiness.**

## K. Risk-Management Review

Fail-closed throughout; canonical single policy (`config/risk_policy.yaml`) schema-validated and
SHA-versioned; caps: risk 0.5%/trade, position 10%, heat 4%, sector 30%, correlated 35%,
daily 1.5% / weekly 4% / total DD 8%, loss-streak 3, min R:R 1.5, min conf 0.6; circuit-breaker
sizing scalar wired in. **But** the concentration/drawdown/loss-streak caps **can't fire on the
real submit path** because `PortfolioState` is built empty (P0-3), and several declared caps are
dead code (P1-11).

## L. Execution-Realism Review

Covered in H (backtest) and I (live path). The two highest-impact realism gaps: **(1)** headline
engine models no costs and fills same-bar close; **(2)** live path infers rather than verifies
the protective stop.

## M. AI-Brain Review

Structured/typed proposals with `evidence_gaps`, `red_team_risks`, and a `confidence_ceiling`
capped at "moderate" when evidence is thin (`scripts/.../super_smart_recommender.py:218-233`);
prices/targets pulled from DB/artifacts, never invented; a calibration journal grades forecasts
vs realized prices. **Structurally cannot size or submit.** Weakness: the enforcement test
doesn't scan the real tool module (P1-9), and there's no automated price-citation cross-check on
free-text theses.

## N. Memory & Learning Review

Source-separated recall (replay labeled INDICATIVE), sample-size `n` on every number, auditable
example signal ids, 6-month half-life decay. **But** confidence inflates on repetition without
outcome gating (P1-5), there is no demotion-on-contradiction, and the "never misreports" proof is
narrow (P1-6).

## O. Dashboard & Reporting Review

The JSON artifacts are refreshingly **truthful** (survivorship caveats, "INDICATIVE" labels,
0-paper-trade honesty, BLOCKED/REJECTED verdicts baked in). The one place truth leaks is any
"dollars made" sourced from the **costless** `backtest/engine.py` (P0-5) — ensure the app never
renders that as expected live performance.

---

## P. Test-Coverage Gaps (highest value first)

1. `classify()` ≡ `fires()` parity (or explicit divergence) — would catch P1-2.
2. Post-fill protection **in `OrderManager` itself** (incident on `protective_order_attached:False`).
3. Verified (not inferred) live stop existence; raise on partially-attached bracket.
4. `OrderManager(mode=None)` + `TB_MODE=live` still cannot submit.
5. Routine/doc guard: fail if `routines/*.md`/`CLAUDE.md` contain raw order JSON or wrapper order verbs.
6. Importability/packaging test (would have caught missing `data/`).
7. Effective-N / PBO **gating** test: a high-PBO or low-eff-N setup must be downgraded, not enabled.
8. Survivorship-impact test: edge must degrade on a delisted-inclusive universe.
9. Walk-forward non-overlap + benchmark-exclusion.
10. Concentration/drawdown caps fire **through `order_manager`** with a real `sector_map`.
11. `.env` secret guard (CI).
12. Costs applied in `backtest/engine.py`; next-bar fill asserted (or docstring fixed).

## Q. Red-Team Findings (against the prompt's challenges)

- *Prove no overfit* → **FAILS** honestly: PBO 92.9% (`lab/gauntlet.py:84`).
- *Prove no look-ahead* → **PASSES** in the production path (`lab/validate.py`), **except**
  `backtest/engine.py` same-bar-close fill.
- *Prove not survivorship-biased* → **FAILS** by the system's own admission (`survivorship_bias_free:false`).
- *Prove live is blocked* → **PASSES**, strongly (Section B).
- *Prove AI can't override risk* → **PASSES** by construction (under-tested on the biggest module).
- *Prove paper evidence is real* → **FAILS**: 0 resolved trades.
- *Prove slippage is included* → **FAILS** for the headline engine; partial for engine B.
- *Prove dashboard doesn't lie* → **MOSTLY PASSES**; risk is the costless "$ made" figure.
- *Prove final verdict stays blocked when evidence is thin* → **PASSES**: BLOCKED.

## R. Brain Upgrade Architecture (target)

Keep the 12-layer separation the system already gestures at, and fix the **wiring + inputs**:
Data Brain (PIT + delisted) → Feature Brain (no-lookahead, already good) → **one** Strategy Brain
(single canonical signal) → Risk Brain (fed *real* PortfolioState) → Execution Brain (cost-real
sim + verified live stops) → Portfolio Brain (live correlation/cluster) → Validation Brain
(gates consume PBO/eff-N/cost-stress) → Paper Brain (scale forward evidence) → Memory Brain
(outcome-gated) → Meta-Learning (demotion on contradiction) → Red-Team (already strong) →
Decision Brain (rank vs benchmark **and cash**).

## S. Implementation Roadmap

- **Phase 1 — Restore exercisability.** Ship the `data/` package; get `pytest` green in a clean
  venv; add the packaging/importability test. *(Nothing else is trustworthy until the safety net
  runs.)*
- **Phase 2 — Make the caps bind.** Populate `PortfolioState` in `order_manager.py` with real
  `sector_map`/equity/PnL/drawdown/loss-streak; add end-to-end tests that each cap fires.
- **Phase 3 — Verify protection.** Post-fill: confirm the live stop *order* exists; incident +
  block on partial/failed attach; wire scheduled broker reconciliation into `ops/serve.py`.
- **Phase 4 — Honest backtest.** Add costs + next-bar fill (or fix docstring) to `engine.py`;
  gap-through-stop fills at the gap; make PBO/eff-N/cost-stress **gate** verdicts.
- **Phase 5 — One signal.** Merge `classify()`/`fires()`; parameter-sensitivity test that gates.
- **Phase 6 — PIT universe.** Delisted-inclusive, point-in-time; re-run everything; expect the
  edge to shrink — that's the point.
- **Phase 7 — Forward paper at scale.** Multi-ticker, multi-regime, ≥50 resolved fills.
- **Phase 8 — Decision dossiers** that rank trades vs QQQ/SMH/**cash**.
- **Phase 9 — Outcome-gated memory** + demotion on contradiction.
- **Phase 10 — Dashboard truth** (never render costless "$ made" as live-expected).
- **Phase 11 — Close the test gaps** in Section P; harden CI.
- **Phase 12 — Human-review pack** only after Phases 1–7 produce real evidence.

## T. Files to Add
- `data/` package (or confirm + document its absence) · `tests/test_packaging_importable.py`
- `tests/test_portfolio_caps_bind_through_order_manager.py`
- `tests/test_post_fill_protection.py`, `tests/test_stop_verified_not_inferred.py`
- `tests/test_signal_parity_classify_vs_fires.py`, `tests/test_param_sensitivity.py`
- `tests/test_pbo_effn_gating.py`, `tests/test_routine_doc_no_order_json.py`, `tests/test_env_no_secrets.py`
- `backtest/costs.py` (shared cost/slippage model for engine.py)

## U. Files to Modify
- `execution/order_manager.py` (PortfolioState wiring; post-fill verification; explicit mode arg)
- `backtest/engine.py` (costs + next-bar fill / docstring) · `backtest/trade_sim.py` (gap fill)
- `backtest/walk_forward.py` (non-overlap + exclude benchmark) · `scripts/calibration.py` (consume PBO)
- `scripts/recommend.py:459` (dead diversification cap) · `scripts/collective/memory.py:70-72` (outcome-gate)
- `CLAUDE.md` + `routines/*.md` (remove order-placement-via-wrapper drift) · `.env` → `.env.example`

## V. Tests to Add
See Section P (1–12). Priority: 2, 3, 6, 7, 10.

## W. Reports to Generate
- `reports/benchmark-*.json` (persist the QQQ/equal-weight comparison that's computed but not saved)
- `reports/pbo.json`, `reports/effective-sample.json` as **gating** inputs
- A survivorship-/cost-corrected replay scorecard alongside the current one

## X. Final Verdict

```
Final verdict:          LIVE_BLOCKED   (system already enforces this — correctly)
Current mode:           paper (default); backtest/research for the engines
Live trading:           UNREACHABLE without writing new code (strong, layered, CI-enforced)
Paper trading:          mechanism ready; evidence ≈ zero (0 resolved fills, 1 ticker, 1 week)
Backtest status:        rigorous tooling, survivorship-biased + cost-light inputs; no proven edge
Main money-making strength:  disciplined idea-generation + an honesty/validation apparatus that
                             refuses to fool itself (rare and valuable)
Main money-losing risk:      acting on a survivorship/overfit artifact (PBO 92.9%); and on the
                             live path, concentration/drawdown caps not binding + unverified stops
Top blockers:           edge unproven (P0-1/2), caps starved of data (P0-3), stop not verified
                        (P0-4), costless headline engine (P0-5), no forward evidence, data/ missing
Top upgrades:           Phases 1–4 above (exercisability → bind caps → verify stops → honest costs)
Safe next action:       install deps in a venv, run the suite, ship data/, then collect real
                        forward-paper fills at scale
Forbidden next action:  enabling live, weakening any gate, or treating the replay edge as real
```

_Bottom line: the engineering of **restraint** here is world-class; the evidence of **edge** is
not there yet. Keep it blocked, make the caps actually bind, stop trusting the survivorship
replay, and go earn real forward-paper evidence. — Independent review, 2026-06-03._
