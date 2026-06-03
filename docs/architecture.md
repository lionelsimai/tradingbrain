# TradingBrain Architecture

Layered, single-order-path design. The AI proposes; the safety stack decides.

```
strategies/ (SignalCandidate)        agents/ (propose/explain only, no broker)
        |                                   |
        v                                   v
   scorecards/  ──(evidence by source)──> calibration
        |
        v
  execution/order_manager  ── the ONE order path ──────────────────────────┐
   ├─ safety/config_guard   (mode; live fails closed)                       │
   ├─ safety/kill_switch    (master halt + pauses)                          │
   ├─ data/quote_validator + market_calendar  (fresh, in-session, sane)     │
   ├─ safety/risk_gate      (policy-only sizing + limits)                   │
   ├─ portfolio/portfolio_engine (heat/sector/correlation/cash)            │
   ├─ journal/event_store + safety/trade_journal (audit every step)         │
   └─ execution/broker_base ─> paper_adapter | NullBroker | DisabledLive    │
                                   |                                        │
                          execution/reconciliation  <───────────────────────┘
                          execution/protective_orders (stop/target)
                          ops/incident + monitoring (alerts/metrics/health)
```

- **Canonical risk**: `config/risk_policy.yaml` (only active source).
- **DB**: `database/` (versioned schema + migrations + contracts).
- **Research rigor**: `lab/` (no-look-ahead proof, PBO, DSR, benchmarks).
- **Modes**: backtest/research (no orders) · paper (default) · live (disabled).
