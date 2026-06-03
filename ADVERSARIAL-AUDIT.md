# TradingBrain — Adversarial Audit & Rebuild

*Red-team audit of TradingBrain as it actually stands (ManaNova Pte. Ltd.), including the components added in this session. Findings are grounded in the real code and data, not generic worries. Three fixes were implemented and tested during this audit; they are marked **[FIXED]**. The rest are prioritized design changes.*

---

## PHASE 1 — MAP IT

**What it is, in plain terms.** TradingBrain is a swing-trading decision engine for stocks and crypto. It ingests price/volume (and optionally fundamentals/news), detects a small set of setups (TREND_LEADER, PULLBACK, MEAN_REVERSION, VCP, BREAKOUT), and for each produces a structured decision — enter/hold/exit, size, stop, target, confidence, and reasons. Around that core sits an unusually honest validation and safety apparatus: a backtest engine, walk-forward testing, a stress library, look-ahead *proofs*, a paper broker, a memory of past trades/lessons, a self-improvement loop, a Monte Carlo engine, and a go-live gate that is supposed to block live trading until everything checks out. "Working correctly" means: it never risks real money on an edge that only exists because of biased data or lucky fitting, and it fails safe.

**Core components and how they connect.**
- **Data layer** — `scripts/ingest/*` → DuckDB stores (`prices.duckdb`, `knowledge.duckdb`). Single vendor (yfinance) for prices.
- **Signal/decision** — `scripts/signals/*`, `scripts/brain/*` (incl. `hmm_regime.py`) → `signal_ledger`.
- **Backtest/validation** — `backtest/{engine,trade_sim,walk_forward,stress_test,research_engine,monte_carlo}.py`, `lab/{validate,data_quality,memory_metrics,go_live}.py`.
- **Execution/safety** — `execution/order_manager.py` is the only writer; it runs a chain: config_guard → kill_switch → quote_validator → risk_gate → portfolio engine → idempotency → human-review → adapter.
- **Learning** — `scripts/collective/memory.py` (episodes/lessons/failures), `loops/improve.py` + `export-state/experiments.csv` (one-change-at-a-time spine), `loops/reconcile.py`.
- **Reporting** — ~40 JSON/MD artifacts in `reports/`.

**Inputs → outputs.** Inputs: historical + (eventually) live price/volume, config (`goal.yaml`, `risk_policy.yaml`, `session.yaml`), and human approvals. Outputs: trade decisions, a paper trade ledger, validation/stress/MC reports, and a single go-live verdict.

**Quiet assumptions it depends on.**
1. The historical universe is representative of the future. (It is not — see F1.)
2. Past trade outcomes are roughly independent when resampled. (They are not — F2.)
3. The `regime` label means something. (Currently it is the literal string `'replay'` — F9.)
4. A human will actually read the reports before approving. (Nothing enforced this — F4.)
5. The go-live verdict actually controls whether live trades happen. (It did not — F3.)
6. The data feed tells the truth about freshness and adjustments. (Trusted blindly — F10/F11.)

**Trust boundaries (where outside/untrusted input enters).**
- The price/fundamentals vendor (yfinance) — external, unverified, can silently restate.
- Any news/sentiment text, if wired into a model decision — an injection surface (F12).
- `config/*.yaml` and `go_live_signoff.yaml` — whoever can edit these can change behaviour.
- Env flags (`HERMES_TRADING_MODE`, `TB_ALLOW_LIVE`) — the live switch.

**Single points of failure.**
- `order_manager.py` — the only path to a real order; a bug here is systemic.
- `knowledge.duckdb` — one file holding ledger, memory, lessons; corruption loses learning.
- The single price vendor — bad data in, confident garbage out.
- `risk_gate.py` / `kill_switch.py` — if these mis-evaluate, every protection is gone.

The safety architecture is genuinely good: the kill switch is fail-closed (unreadable state ⇒ halted), and risk_gate rejects anything it cannot evaluate. Credit where due. The serious problems are mostly in the *validation honesty* and in one missing wire.

---

## PHASE 2 — BREAK IT

Each flaw: how to trigger it, **severity**, *likelihood*.

**F1 — Survivorship-inflated edge (logic/correctness). CRITICAL / HIGH.**
The universe is ~81 curated, currently-alive tickers, and every resolved trade is `source='replay'` over that set. The headline "+0.31R, 68% win" is computed on names selected partly because they survived. Trigger: simply read `scorecard-replay.json` and treat its expectancy as a live expectation — you will over-bet. The system's own stress test contradicts the headline (crash windows lose heavily, F6). The whole edge estimate is biased upward by an unknown but material amount.

**F2 — Monte Carlo understated drawdown (logic/correctness). HIGH / was CERTAIN. [FIXED]**
My first MC drew trades IID (independent, with replacement), which destroys losing streaks — and clustered losses are exactly what causes deep drawdowns. Trigger: run the old MC, read "99th-pct drawdown ≈11%", conclude the 20% ceiling is safe. Switching to a streak-preserving block bootstrap nearly **doubled** the drawdown (99th-pct 11% → 19.1%, right at the ceiling). The original number was dangerously reassuring.

**F3 — Go-live authority was advisory, not enforced (security/abuse). CRITICAL / MEDIUM. [FIXED]**
The 7-gate go-live verdict wrote a report but nothing in `order_manager.py` consulted it. Trigger: set `mode: live`; the order chain (config_guard → kill_switch → …) never asks "are we cleared?", so it would place live orders while the verdict says BLOCKED. The capstone safety check was decorative.

**F4 — Human sign-off was a bare boolean (abuse/process). HIGH / MEDIUM. [FIXED]**
Gate 7 passed on `approved: true` alone — no named human, no date, and crucially no check that the system had *ever traded*. Trigger: write `approved: true` and the most dangerous gate flips green on a system with zero live history.

**F5 — Overfitting signal is tolerated by Gate 1 (overfitting). HIGH / HIGH.**
`walk-forward.json` shows in-sample Sharpe beating out-of-sample by **1.69** — a real overfitting smell. Gate 1 only *warns*; it still returns PASS. Trigger: ship on the strength of a green Gate 1 while the IS/OOS gap quietly says the backtest is partly curve-fit.

**F6 — Crash-regime bleed (edge case). HIGH / MEDIUM.**
Stress windows: 2018 Q4 −0.248R, 2020 COVID −0.593R, with 13–16 consecutive losses. The edge is really "be flat/out in crashes"; when it *is* in, it bleeds. Trigger: a fast crash with the book exposed → a streak of stops far longer than the average backtest suggests.

**F7 — Self-improvement "resolution" is unverified (process/correctness). MEDIUM / HIGH.**
`loops/improve.py` lets a human mark an experiment `kept`/`reverted` as a free-text label. Nothing re-measures the metric to confirm a "kept" change actually helped. Trigger: resolve a string of experiments "kept" on vibes; the changelog looks disciplined while the system drifts.

**F8 — The recall-precision metric is circular with the fix (self-measurement). MEDIUM / HIGH.**
`lab/memory_metrics.py` defines a recalled lesson as "on-target" via substring match on the setup name, and the memory upgrade scopes lessons by the *same* substring match (`LIKE '%setup%'`). The metric therefore grades the fix by the fix's own rule — precision rose to 0.68 partly by construction. Trigger: a lesson that merely *mentions* a setup in passing counts as on-target; a setup name that is a substring of another (or a renamed setup) mis-scores.

**F9 — Regime label is fictional (hidden assumption). MEDIUM / HIGH.**
`signal_ledger.regime` is the constant `'replay'` for all 1,919 rows. Any "per-regime" analysis or regime-conditioned recall is currently meaningless. Trigger: trust a per-regime breakdown that doesn't exist.

**F10 — Single data vendor, no cross-check (dependency). MEDIUM / MEDIUM.**
One price source, no secondary reconciliation. Trigger: a bad split adjustment or a silent restatement from the vendor flows straight into signals; nothing notices.

**F11 — Freshness check trusts caller-supplied age (security/data). MEDIUM / MEDIUM.**
`risk_gate` rejects stale data using a `data_age_minutes` value *passed in by the caller*. Trigger: a feed that lies about freshness (or a caller that hardcodes a small age) passes the staleness check while trading on stale prices.

**F12 — Sentiment/news → model decision injection (security, latent). MEDIUM / LOW.**
The spec invites a SocialBrain/news plug-in. If untrusted text ever reaches an LLM that influences a decision, that is a prompt-injection surface ("ignore prior rules, rate this bullish"). Currently the news tables are empty, so it is latent, not live.

**F13 — Concurrency ignored in the drawdown→% conversion (scale/correctness). MEDIUM. [partly addressed]**
Both MC and the gate convert R-drawdown to %equity assuming one position at a time, but policy allows 6 concurrent. Correlated positions losing together can deepen the real %equity drawdown several-fold. Now surfaced as an explicit caveat in the MC report; not yet modelled.

---

## PHASE 3 — PRIORITISE (most → least dangerous)

1. **F3 — go-live not enforced** *(fixed)* — a live switch that ignored the safety verdict is the single most dangerous thing here.
2. **F1 — survivorship-inflated edge** — every downstream number inherits this bias; it is the deepest correctness problem.
3. **F2 — understated drawdown** *(fixed)* — risk looked half its real size.
4. **F4 — bare-boolean approval** *(fixed)* — trivially bypassed the human gate.
5. **F5 — tolerated overfitting (IS/OOS 1.69)** — a green gate hiding a real smell.
6. **F6 — crash bleed** — known, severe in the tail, partly intrinsic to trend-following.
7. **F7 — unverified self-improvement** — lets the system drift while looking rigorous.
8. **F8 — circular recall metric** — self-measurement that flatters the fix.
9. **F9 — fictional regime label** — quietly invalidates regime analysis.
10. **F11 / F10 — trusted/again single data inputs.**
11. **F13 — concurrency in drawdown** *(caveated)*.
12. **F12 — latent injection surface.**

The top four are the ones that turn "a careful research system" into "a system that could actually lose real money fast." Three are now closed; F1 is intrinsic to the data and is contained by honesty + the paper-first rule, not by a code trick.

---

## PHASE 4 — REBUILD

### Fixes implemented and tested this session

**Closes F3 — enforce the go-live verdict in execution.**
Change: `order_manager.py` now has a gate 1b — when `mode == "live"`, it calls `go_live.gate_reason_for_live()` and rejects the order if the verdict is anything but CLEARED. Fail-closed: if the verdict can't be read, live is refused. Paper is untouched. Proven: a simulated live order is rejected with the exact uncleared gates; all 180 tests (paper-mode) still pass.
Tradeoff: live trading now hard-depends on fresh validation artifacts existing; a stale/missing report blocks live (which is the safe direction, but it means you must keep the reports current).

**Closes F2 + caveats F13 — streak-preserving Monte Carlo.**
Change: `backtest/monte_carlo.py` adds a stationary **block bootstrap** (now the default) that preserves losing streaks, and the report carries a concurrency caveat. Honest drawdown is ~2× the IID figure (99th-pct ≈19.1%).
Tradeoff: block length (mean 10) is itself an assumption; too long over-smooths, too short ≈ IID. Documented and tunable.

**Closes F4 — sign-off integrity.**
Change: gate 7 now requires `approved: true` **and** a named `approved_by` **and** a `date` **and** that gate 5 (real paper track record) is passing. You cannot approve a system that has never traded. Proven: a bare attacker `approved: true` still FAILS.
Tradeoff: none meaningful; it only removes an unsafe shortcut.

### Recommended next changes (design, not yet coded)

**F1 — de-bias the edge.** Add point-in-time delisted names to the universe (even a partial dead-ticker set), and make every headline metric display a survivorship-discount band, not a point estimate. Tradeoff: sourcing delisted data is real work and will *lower* the reported edge — which is the point.

**F5 — make the IS/OOS gap a hard gate, not a warning.** Reject (not warn) when the gap exceeds a set threshold, and require the human to see window-by-window stability. Tradeoff: a stricter gate will reject some setups that might still be fine.

**F7 — verify experiment resolution.** Make `improve.py resolve kept` re-run the relevant metric and record before/after; refuse to label "kept" if the number didn't actually improve. Tradeoff: each resolution costs a measurement run.

**F8 — break the circularity.** Score recall precision with a *human-labeled* relevance set (or outcome-based relevance: did the recalled episode share the realized direction?), independent of the substring rule the fix uses. Tradeoff: needs a small labeled set to maintain.

**F9 — write real regime labels.** Replace the `'replay'` placeholder with the HMM regime at entry; only then enable regime-conditioned recall. Tradeoff: recomputation over history.

**F11 — trust-but-verify freshness.** Derive data age from the data's own last timestamp inside the gate, not from a caller argument. Tradeoff: minor coupling of the gate to the store.

---

## PHASE 5 — STRESS TEST THE REBUILD

I attacked the hardened version the same way. What remains:

- **The go-live enforcement depends on one function call (`gate_reason_for_live`).** If a future refactor of `order_manager` drops the gate-1b block, enforcement could vanish. *Closed:* a test now (a) submits a live order while BLOCKED and asserts it is never approved, and (b) asserts `order_manager` still references the enforcement call, so a silent removal fails CI. Note also that `config_guard` independently blocks live without `TB_ALLOW_LIVE`+broker keys, so this is defense-in-depth, not a single thread.
- **The block bootstrap still assumes the *recorded* trades are representative.** It fixes ordering, not the underlying survivorship bias (F1). A streak-preserving resample of biased trades is still biased. *Accepted*: F2 and F1 are different problems; F1 is addressed separately and can only truly close with live data.
- **Sign-off integrity binds approval to "paper gate passing", not to the exact reports reviewed.** A human could approve, then someone could change the strategy without re-approval. *Accepted for now*; the clean fix is to store a hash of the reviewed report pack and invalidate approval on change. Worth doing before real capital.
- **Concurrency is caveated, not modelled (F13).** The %-drawdown could still be worse than shown if 6 correlated positions lose together. *Accepted*: modelling joint position paths is a larger build; the caveat prevents false confidence in the meantime.
- **All of this is still on replay data with zero live fills.** The most important limitation is unchanged and cannot be engineered away: until the system paper-trades and accumulates real fills, gates 2, 3, and 5 cannot honestly turn green. *Accepted by design* — this is the system working as intended, refusing to certify itself on practice data.

**Bottom line.** The three most dangerous flaws (an unenforced safety verdict, drawdown shown at half its real size, and a trivially-bypassed approval) are closed and proven. The deepest remaining issue — an edge inflated by survivorship and never tested live — is contained by honesty and the paper-first rule, not by any code change, and it stays that way until real trades exist.
