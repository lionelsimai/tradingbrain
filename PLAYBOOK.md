# TradingBrain Collective — Playbook

> The living record of the org getting smarter. Updated each cycle. Last: cyc_20260529_231936.

## Deployable strategies (trade live, full size)
- **PULLBACK** — OOS 0.297R · risk APPROVED
- **MEAN_REVERSION** — OOS 0.438R · risk APPROVED
- **TREND_LEADER** — OOS 0.106R · risk APPROVED
- **VCP** — OOS 0.148R · risk APPROVED

## Provisional (Iterate — half size, flawed)
- **BREAKOUT** — WOUNDED: Survivorship bias: universe excludes delisted names — live edge likely lower.

## Rejected / dead ideas (do not re-test without new conditions)
- (none)

## Known traps (top reinforced lessons)
- _data_integrity_: Universe is survivorship-biased; treat all backtest edges as INDICATIVE and discount live expectations until point-in-time delisted data is sourced. (×2)
- _regime_: BREAKOUT has non-positive expectancy in regimes ['bear']; gate it off there. (×2)
- _red_team_: BREAKOUT: Survivorship bias: universe excludes delisted names — live edge likely lower. (×2)
- _red_team_: BREAKOUT: Walk-forward efficiency -20.69: OOS is a poor fraction of IS — overfit risk. (×2)
- _red_team_: BREAKOUT: Negative expectancy in regimes: ['bear'] — gate these off. (×2)

## Data integrity
- Survivorship-bias-free: **False** → results are **INDICATIVE only**.
