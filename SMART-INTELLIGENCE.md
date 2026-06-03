# Adaptive Intelligence Core

> The upgrade that makes TradingBrain *smarter*, not just bigger — and does it
> without touching the honest base engine or the fail-closed risk path.

The base engine (`scripts/recommend.py`) scores conviction from six pillars and
caps everything at "moderate" until a live track record exists. That is honest
but **static**: the same setup gets the same score in a bull or a bear, the
score is an arbitrary 0–100 with no probability behind it, and conflicting
pillars are silently averaged. The Adaptive Intelligence Core adds four
reinforcing capabilities as a **composable overlay** (the same pattern as
`super_recommender` / `super_smart_recommender`), so the base engine and the
`safety/` apparatus are untouched and all existing tests stay green.

Run it:

```bash
python3 -m scripts.smart_recommender            # enriched picks + watch list
python3 -m scripts.smart_recommender --json     # raw structured output
python3 -m scripts.smart_recommender --equity 50000 --top 5
```

Output is written to `reports/smart-recommendations.{json,md}`. Research-only; it
never executes, never sizes up, and never lifts the honest cap on replay data.

## The four capabilities (`scripts/intelligence/`)

1. **Outcome calibration — the brain learns what its scores mean.**
   `conviction_calibration.py` + `outcomes.py`. Conviction is recalibrated
   against the **real, source-separated track record** (`scorecard-live.json` vs
   `scorecard-replay.json`). Two layers: a Beta-Binomial **Bayesian shrinkage**
   over each setup's realized win-rate/expectancy (so a 28-trade setup is
   trusted and a 3-trade one is pulled to the base rate), and an **isotonic
   reliability curve** that auto-activates once a per-pick `conviction-outcomes.json`
   ledger exists. A pick now carries a calibrated `p_win` and `expected_R`, not
   just a number.

2. **Regime adaptation — context-aware weights and sizing.**
   `regime_adaptive.py`. Consumes the brain's existing **causal** regime
   (`hmm-regime.json`) and (a) tilts the *positive* alpha-pillar contributions
   (lean into trend/momentum in a stable bull; fade them and favour quality in a
   bear), and (b) emits a position-size **throttle in [0.25, 1.0]** combining
   target exposure with volatility targeting.

3. **Uncertainty-aware fusion — honest about disagreement.**
   `uncertainty.py`. Treats the pillars as signed votes and **discounts**
   conviction when they conflict (a +25 trend against a −25 regime is no longer
   a confident middle), returning a credible interval `[lo, hi]`.

4. **Sector/peer relative strength — stock-specific edge.**
   `relative_strength.py`. A stock's trailing return minus its **sector peers'**
   median (not just vs SPY), as a bounded ±6-point adjustment — isolates a name's
   own edge from its sector's beta.

## Safety & honesty invariants (enforced by `tests/test_intelligence_*.py`)

These are not aspirations; they are unit-tested:

| Invariant | Where | Test |
|---|---|---|
| Moderate cap is **never** lifted on anything but LIVE evidence | `conviction_calibration.lifts_cap`, `smart_core` cap | `test_replay_evidence_never_lifts_cap`, `test_honesty_cap_holds_*` |
| Size throttle is **always ≤ 1.0** (can only reduce risk) | `regime_adaptive.size_throttle` | `test_size_throttle_never_exceeds_one`, `test_low_vol_never_increases_size` |
| Small samples are **shrunk** toward the base rate | `Calibrator._shrink` | `test_bayesian_shrinkage_pulls_small_samples_to_base` |
| No evidence ⇒ calibrator is a **no-op** | `Calibrator.calibrate` | `test_calibrator_no_evidence_is_noop` |
| Conflicting pillars **lower** conviction; hostile regime lowers it more | `uncertainty`, `smart_core` | `test_unanimous_pillars_low_penalty`, `test_smart_throttle_and_bear_below_bull` |
| Everything **degrades** without crashing on empty data | all modules | `test_degrades_on_empty_inputs` |

No look-ahead: the regime is point-in-time, evidence is realized/past, and
relative strength uses trailing returns.

## What it looks like (same NVDA BREAKOUT, three regimes)

```
BASE six-pillar raw conviction: 70

Bull   smart 60 (moderate)  p_win 74%  exp +0.26R  agreement 1.00  size x0.64
       tilt: trend +3.8, momentum +2.0 · capped at 60 (no live record)
Bear   smart 45 (weak)      p_win 74%  exp +0.26R  agreement 0.67  size x0.25
       tilt: trend −10, momentum −10 · uncertainty −10.5 (pillars conflict)
Crash  smart 45 (weak)                              agreement 0.67  size x0.25
```

The brain now leans in when the regime supports it, shrinks and de-rates the same
setup when it doesn't, grounds its confidence in its actual 74% replay win-rate,
and still refuses to call anything "strong" until real fills exist.

## Files

```
scripts/intelligence/
  __init__.py                 # package + MODERATE_CAP (asserted == recommend.MODERATE_CAP)
  regime_adaptive.py          # regime profile, pillar tilts, size throttle
  uncertainty.py              # signed-vote fusion, disagreement penalty, interval
  outcomes.py                 # source-separated live/replay evidence loader
  conviction_calibration.py   # Bayesian shrinkage + isotonic reliability curve
  relative_strength.py        # sector/peer RS
  pillars.py                  # per-pillar point breakdown (mirrors recommend.py)
  smart_core.py               # orchestration -> enriched read
scripts/smart_recommender.py  # CLI overlay (reuses recommend.py end to end)
tests/test_intelligence_core.py
tests/test_intelligence_relative_strength.py
```

## Roadmap (next, all designed to stay honest)

- **Activate the reliability curve** by logging `(raw_score, realized_R)` per
  pick to `reports/conviction-outcomes.json` from the forward-paper loop.
- **Post-earnings drift** signal (the cleanest single-name anomaly).
- **Online pillar-weight learning** from realized outcomes, walk-forward gated.
- **Correlation-aware portfolio heat** and explicit factor-exposure limits.
