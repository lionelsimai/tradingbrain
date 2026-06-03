# TradingBrain v2 — Hardening Pass

This pass implemented the recommendations left open by the adversarial audit and
the earlier work, found and fixed new gaps, and added tests for each. Nothing
here inflates the system; several changes make it *more* honest. Full suite: 193
tests green (up from 187).

## What was fixed (each tested)

1. **Real regime labels (audit F9).** The ledger's `regime` field was the literal
   string `'replay'` on all 1,919 rows — every "per-regime" view was fiction. New
   `scripts/brain/regime_label.py` computes a real, point-in-time regime from SPY
   (bull / bear / chop / high-vol / crash), correctly tagging COVID and the GFC as
   crashes. Backfilled the whole ledger and wired it into live signal emission.

2. **Regime-aware recall + lesson decay.** Memory recall now actually uses the
   regime (it was a no-op before) and exposes a per-regime breakdown — e.g.
   TREND_LEADER wins ~71% in bull, ~97% in high-vol-bull, ~63% in chop, instead of
   one blended number. Lessons now decay with age (6-month half-life) so stale,
   dead-regime lessons stop dominating.

3. **Overfitting is now a hard gate (audit F5).** The in-sample-vs-out-of-sample
   Sharpe gap (1.69) used to only print a warning. It's now a hard go-live gate
   with a configurable limit (default 1.5), so the current gap correctly FAILS.

4. **Sign-off bound to the reports (audit Phase 5).** Human approval now requires a
   hash of the exact report pack reviewed. If any validation report changes after
   approval, the approval is automatically invalidated — you can't approve once and
   silently change the strategy.

5. **Non-circular memory metric (audit F8).** The old recall-precision metric
   graded the fix by the fix's own substring rule. Added an independent fidelity
   check that recomputes each setup's real numbers and confirms recall reports them
   truthfully (currently 100%).

6. **Picker wired into the 24/7 paper loop.** The recommendation engine, regime
   backfill, Monte Carlo, and the go-live verdict now refresh automatically each
   cycle, so running it in paper mode keeps every report and the verdict current —
   and starts producing the real fills everything is gated on.

7. **Survivorship surfaced, not hidden (audit F1).** Recommendations now state
   plainly that 0% of the universe is delisted, so replay edge is an optimistic
   ceiling (a prudent assumption is real edge is materially lower). The true fix —
   adding point-in-time delisted names — needs a data source and is noted below.

8. **Self-improvement keeps are now verified (audit F7).** Marking an experiment
   "kept" now checks the live edge and tags the keep UNVERIFIED if the metric did
   not actually improve — the loop can no longer drift on a label alone.

## Honest verdict, refreshed
Go-live is still **BLOCKED**, now for sharper reasons: zero live trades (gate 5),
the overfitting gap (gate 4, newly enforced), and no human sign-off (gate 7).
Monte Carlo and stress remain "needs human." This is the system working.

## What's still open (honest)
- **F11 — data-freshness trust:** the staleness check still trusts a caller-supplied
  age rather than deriving it from the data's own timestamp. Touches the live path;
  deferred to avoid destabilizing execution without a dedicated test.
- **F1 (full):** truly de-biasing the edge requires sourcing delisted/dead tickers
  (a data-vendor task, not a code change). Until then, survivorship is surfaced and
  banded, not removed.
- **The unmovable one:** zero live trades. No code change closes gates 2/3/5 — only
  paper-trading does. The loop and hosting now drive exactly that.
