# Point-in-Time Data Plan (honesty about bias)

## Current state (reported as FALSE in every backtest)
- `survivorship_bias_free: false` — universe = ~77 names that exist TODAY.
- `point_in_time_universe: false` — no historical index membership; delisted names absent.
- Corporate actions: split/dividend adjustment via vendor (yfinance) adj_close; not audited.

## Why it matters
Win rates and expectancy are optimistic; the swing system's stops limit damage,
but absolute edge numbers must NOT be read as live alpha. Calibration down-ranks
biased evidence and the live gate ignores it entirely.

## Roadmap to point-in-time
1. Acquire a delisting-inclusive dataset (e.g. CRSP / Norgate / Sharadar).
2. Reconstruct historical universe membership per date.
3. Re-run stress/research with delisted names included.
4. Flip the report flags only when genuinely true.

Until done: reports say false, and no report may claim institutional-grade alpha.
