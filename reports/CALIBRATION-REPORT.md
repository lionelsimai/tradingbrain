# TradingBrain — 10-Year Stress Test & Calibration

> Generated 2026-05-29 · 23,216 simulated trades · history through 2026-05-29

Every setup is fired on past-only data, then the **full trade plan** (structure-based stop + two scaled targets) is simulated bar-by-bar until stop/target/20-day timeout. Results in **R-multiples** (1R = initial risk).

## Setup edge (full history, ranked by expectancy)

| Setup | Trades | Win % | Expectancy | Profit Factor | Max Loss Streak | OOS Expectancy | Verdict |
|---|---|---|---|---|---|---|---|
| MEAN_REVERSION | 904 | 22.8% | +0.681R | 1.89 | 20 | +0.904R | ✅ ENABLED |
| PULLBACK | 541 | 37.5% | +0.669R | 2.09 | 15 | +0.588R | ✅ ENABLED |
| VCP | 1,559 | 54.5% | +0.267R | 1.6 | 14 | +0.406R | ✅ ENABLED |
| BREAKOUT | 1,462 | 72.7% | +0.152R | 1.57 | 7 | +0.291R | ✅ ENABLED |
| TREND_LEADER | 18,750 | 67.6% | +0.149R | 1.49 | 13 | +0.172R | ✅ ENABLED |

## Regime is destiny — expectancy by market regime

The single biggest finding: **longs lose money in bear/crash regimes.** The engine now hard-gates long setups when SPY regime is bear.

| Stress Window | Trades | Win % | Expectancy |
|---|---|---|---|
| 2018 Q4 selloff | 224 | 37.1% | -0.280R |
| 2020 covid crash | 207 | 30.4% | -0.581R |
| 2022 bear | 678 | 38.6% | -0.390R |
| 2025 tariff vol | 1,092 | 71.1% | +0.225R |

## Best setup × regime combinations

| Setup | Regime | Trades | Win % | Expectancy |
|---|---|---|---|---|
| MEAN_REVERSION | chop | 71 | 29.6% | +1.621R |
| MEAN_REVERSION | bull_volatile | 51 | 33.3% | +1.452R |
| PULLBACK | bull_volatile | 93 | 39.8% | +0.891R |
| PULLBACK | euphoria | 342 | 37.1% | +0.699R |
| VCP | bull_volatile | 84 | 64.3% | +0.612R |
| MEAN_REVERSION | euphoria | 758 | 21.8% | +0.563R |
| PULLBACK | chop | 73 | 39.7% | +0.500R |
| BREAKOUT | chop | 227 | 85.5% | +0.290R |
| TREND_LEADER | chop | 1,341 | 73.9% | +0.282R |
| VCP | euphoria | 1,093 | 49.5% | +0.252R |

## Asset class

| Class | Trades | Win % | Expectancy | Profit Factor |
|---|---|---|---|---|
| crypto | 2,035 | 62.9% | +0.162R | 1.47 |
| stock | 21,181 | 64.7% | +0.192R | 1.57 |

## How the engine uses this

- **Gating:** setups with OOS expectancy < +0.05R or < 30 OOS trades are disabled. Longs are suppressed entirely in bear regimes.
- **Confidence weighting:** each setup's live score is scaled by its proven OOS edge × regime-fit multiplier.
- **Grading:** an A-grade now requires positive OOS expectancy in addition to lens confluence and R/R.
- **Retraining:** `backtest/stress_test.py` reruns weekly inside the reflection loop, refreshing `calibration.json`.
