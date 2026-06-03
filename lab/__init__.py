"""TradingBrain research-rigor layer (the 10/10 instrument upgrade).

Modules:
  stats        — gold-standard significance: stationary-bootstrap CI, effective
                 sample size (overlap-aware), Probabilistic & Deflated Sharpe
                 (Bailey & Lopez de Prado), and PBO via CSCV.
  benchmark    — correct benchmarks (QQQ / equal-weight basket) + alpha/beta/IR.
  data_quality — point-in-time price sanity gate.
  provenance   — data + code hashing and a reproducibility manifest.
  validate     — automated no-look-ahead, live==backtest, determinism proofs.
"""
