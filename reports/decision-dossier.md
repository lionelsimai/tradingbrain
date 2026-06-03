# Decision Dossier — cyc_20260529_231936

_Generated 2026-05-29 23:19 UTC · compute 2.2s · data INDICATIVE (survivorship-biased)_

## Goals
- Re-validate the strategy library and rule Deploy/Iterate/Reject
- Distill durable lessons from rejections/wounds into memory
- Refresh the playbook with current best practices + traps

## Rulings (engine → after Red Team + Risk Officer)

Legend: `SURVIVES (n)` / `WOUNDED (n)` — _n_ = number of Red Team findings on that strategy. All `Deploy` verdicts are conditional (see caveat below): paper/reduced-size only until point-in-time delisted-universe data is sourced.

| Strategy | Engine | Red Team | Risk Officer | **Final** |
|---|---|---|---|---|
| PULLBACK | Deploy | SURVIVES (1) | APPROVED | **Deploy — paper/reduced-size until PIT data** |
| BREAKOUT | Iterate | WOUNDED (3) | APPROVED w/ conditions | **Iterate — (1) gate off bear regime; (2) re-run walk-forward to address overfit** |
| MEAN_REVERSION | Deploy | SURVIVES (1) | APPROVED | **Deploy — paper/reduced-size until PIT data** |
| TREND_LEADER | Deploy | SURVIVES (1) | APPROVED | **Deploy — paper/reduced-size until PIT data** |
| VCP | Deploy | SURVIVES (1) | APPROVED | **Deploy — paper/reduced-size until PIT data** |

## Red Team findings

_Universe-wide caveat (applies to all strategies): Survivorship bias — universe excludes delisted names, so live edge is likely lower than shown._

Strategy-specific findings:
- **PULLBACK**: None beyond the universe-wide caveat.
- **BREAKOUT**: Walk-forward efficiency −20.69% (metric: median OOS return ÷ median IS return, as a percent; a negative value means out-of-sample is loss-making while in-sample is profitable — a classic overfit signature). Negative expectancy in regimes: ['bear'] — gate these off.
- **MEAN_REVERSION**: None beyond the universe-wide caveat.
- **TREND_LEADER**: None beyond the universe-wide caveat.
- **VCP**: None beyond the universe-wide caveat.

## Lessons distilled this cycle
- data_integrity: results are indicative, not validated until point-in-time delisted-universe data is sourced.
- BREAKOUT: red-team wounded (3) — see durable lessons below.
- Durable — bear-regime gating: a strategy with negative expectancy in a regime should be gated off in that regime rather than blended into a single blended-regime number, which masks the loss.
- Durable — overfit detection: walk-forward efficiency (OOS÷IS) at or below zero flags overfitting; require positive OOS efficiency before any size-up, and re-run walk-forward after parameter changes.

## Playbook — current best practices + traps
- **Source point-in-time, delisted-inclusive data** before treating any ruling as validated; until then every Deploy stays paper/reduced-size.
- **Score expectancy per regime, not blended.** Gate off regimes with negative expectancy (e.g. BREAKOUT in bear) instead of relying on an all-regime average.
- **Require positive walk-forward efficiency (OOS÷IS > 0)** as a deploy gate; treat ≤0 as an overfit flag and re-run after any parameter change.
- **Trap — survivorship inflation:** backtests on surviving names overstate edge; haircut expectations until corrected.
- **Trap — APPROVED ≠ unconditional:** a Risk Officer pass on a wounded strategy carries its Red Team conditions; the conditions travel with the verdict.

## Biggest risk to these conclusions
- Survivorship-biased universe: live edge is likely lower than shown. Treat all rulings as INDICATIVE until point-in-time delisted-universe data is sourced.