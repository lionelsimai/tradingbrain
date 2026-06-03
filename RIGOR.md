# TradingBrain — Research Rigor & Reproducibility

This is what makes TradingBrain a *research instrument* rather than a backtest
script: every number it reports is **provably free of look-ahead, honest about
overfitting and overlap, benchmarked correctly, and reproducible to the byte.**

## One command rebuilds (and proves) everything

```bash
python3 rebuild.py            # full deterministic rebuild + MANIFEST
python3 rebuild.py --fast     # skip the slow 30y research lifecycle
python3 rebuild.py --seed 7   # set the global RNG seed
```

The pipeline is **gated** — if the correctness proofs or a hard data-quality
failure trip, the build halts before producing numbers you'd be tempted to
trust:

```
0. validate      no-look-ahead proof · live==backtest · determinism   (GATE)
1. data_quality  point-in-time price sanity                            (GATE)
2. stress_test   calibration.json (setup×regime edge, net of costs)
3. research      research-report.json (full lifecycle + PBO/DSR)
4. replay        backfill → resolve → scorecard (live-vs-backtest drift)
5. reconcile     strategy_library status + distilled lessons
6. provenance    hash code+data → reports/MANIFEST.json
```

## The `lab/` rigor layer

### `lab/validate.py` — correctness proofs (run every build)
- **No look-ahead (proof, not promise):** for many (ticker, T) points it corrupts
  *all* data after T (randomly rescales future bars) and asserts the signal,
  feature row, and trade plan at T are **byte-identical**. If any future data
  leaked into a past decision, this fails.
- **live == backtest:** the vectorized backtest detector (`detect_at`) must equal
  the live detector (`detect_setup`) exactly. Currently 0 mismatches over 650+
  checks.
- **determinism:** seeded resampling reproduces bit-for-bit.

### `lab/stats.py` — significance that doesn't lie
- **`effective_sample_size`** — overlapping/autocorrelated trades make N look
  bigger than it is; this discounts it (autocorrelation-adjusted).
- **`stationary_bootstrap_ci`** (Politis–Romano) — confidence intervals that
  respect serial dependence instead of pretending trades are independent.
- **`probabilistic_sharpe_ratio`** & **`deflated_sharpe_ratio`** (Bailey &
  López de Prado) — the DSR deflates each Sharpe against the *expected best*
  Sharpe from the number of strategies tried. This is the multiple-testing tax.
- **`pbo_cscv`** — **Probability of Backtest Overfitting** via
  Combinatorially-Symmetric Cross-Validation (Bailey et al. 2015): how often the
  in-sample-best strategy underperforms out-of-sample. > 0.5 means your
  selection process is worse than random.
- **`min_track_record_length`** — how many trades you'd need before the Sharpe is
  statistically distinguishable from zero.

These are not cosmetic. In the research engine, **a strategy whose Deflated
Sharpe < 0.5 or whose portfolio PBO > 0.5 is automatically downgraded from
Deploy to Iterate** — the overfitting check changes the decision. (BREAKOUT is
currently downgraded for exactly this reason: DSR ≈ 0.44.)

### `lab/benchmark.py` — the right yardstick
A momentum strategy on AI mega-caps must not be scored against SPY (which
flatters it). This compares the strategy's equity curve to **QQQ and the
equal-weight basket** of the traded universe, and reports **alpha, beta,
information ratio, Sharpe, Sortino, and max drawdown** vs each. It will tell you
plainly when the strategy does *not* beat simply holding the basket.

### `lab/data_quality.py` — garbage-in gate
Scans every ticker for non-positive prices, OHLC inversions (classified
material vs benign feed glitches), implausible single-day jumps (unadjusted
splits / bad prints), stale runs, duplicate dates, and thin history. Hard
integrity failures halt the build; coverage issues warn.

### `lab/provenance.py` — reproducibility receipts
Writes `reports/MANIFEST.json`: SHA-256 of the price/knowledge databases, a hash
of all source code, library versions, the RNG seed, and key headline results —
so any number can be traced to the exact code+data that produced it.

## Tests
```bash
python3 -m pytest -q          # 20 tests: 11 core + 9 rigor
```
The rigor suite asserts the no-look-ahead proof, live==backtest, determinism,
effective-N behavior, PBO on noise (~0.5) vs real edge (<0.25), and that the DSR
penalizes additional trials.

## Honest standing limitations (by design, surfaced not hidden)
- **Survivorship bias** — the universe is current AI names; delisted losers are
  absent. Reported in every research verdict's `biggest_risk`. The instrument
  *measures and flags* this; it cannot remove it without delisting-inclusive
  data. Stops cap per-trade damage, which limits (not eliminates) the bias.
- **Single macro-sector** — ~0.32 average pairwise correlation; position-level
  diversification overstates independence. The sector cap is now enforced; the
  universe-level AI-beta concentration remains a property of the mandate.
- **Long-only** — structurally exposed to bear regimes; mitigated by the regime
  gate (`long_gated`) which forces risk-off longs to no-trade.
