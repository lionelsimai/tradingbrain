# Strategy Promotion & Retirement

Stages: idea → research → backtest → replay → paper-probation → supervised-paper → frozen → retired.

Promotion gates:
- research→backtest: hypothesis + explicit entry/exit/stop + failure mode.
- backtest→replay: no leakage (look-ahead proof), cost model, benchmark, sufficient effective_n.
- replay→paper: stable OOS, CI lower bound > 0, not dependent on top winners, PBO low.
- paper-probation→supervised: enough paper trades, acceptable execution quality + drawdown.

Retirement triggers (auto-flag):
- negative expectancy after costs; OOS breakdown; CI lower bound < 0;
  benchmark opportunity cost too high; drawdown breach; repeated stop failures;
  stale evidence source.

Unknown setup → probation, size cap 0.25 (never full size). See `scripts/calibration.py`.
