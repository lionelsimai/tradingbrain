# Live Trading — DISABLED

Live trading is OFF by construction. To even be *considered*, ALL must hold:

1. `config/risk_policy.yaml` → `environment.live_trading_enabled: true` (ships `false`).
2. `TB_MODE=live` AND `TB_ALLOW_LIVE=1` AND `TB_HUMAN_APPROVED=1`.
3. Reconciliation status clear (P1 — not built yet).
4. Forward paper-fill evidence accumulated (none yet).
5. A live broker adapter that is implemented + tested (today `DisabledLiveAdapter` raises).

Until then:
- `OrderManager` runs in `paper` mode; `backtest/research/replay` never submit.
- `execution/broker_base.DisabledLiveAdapter` raises `DisabledLiveTradingError` on construction.
- `config_guard.safe_to_trade("live")` fails closed without the flags.

There is no code path that places a live order today.
