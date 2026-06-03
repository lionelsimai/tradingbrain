# TradingBrain — Operator Runbook

The emergency + routine procedures. Keep this open during any paper/live session.

## Golden rules
- **Default mode is `paper`.** Live trading is refused unless `TB_MODE=live` **and**
  `TB_ALLOW_LIVE=1` **and** broker keys are set **and** the kill switch is clear.
- **The AI only proposes.** The risk gate (`safety/risk_gate.py`) decides size; the
  broker only places what the gate approved. No component may size or place a trade
  on its own.
- When in doubt: **engage the kill switch first, investigate second.**

## Emergency commands
```bash
# STOP EVERYTHING (the big red button) — blocks all new orders immediately
python3 -m safety.operator kill "reason here"

# Resume after you've verified it's safe
python3 -m safety.operator release

# Pause just one strategy or symbol
python3 -m safety.operator pause TREND_LEADER
python3 -m safety.operator pause NVDA
python3 -m safety.operator resume NVDA

# Close all paper positions (requires --yes)
python3 -m safety.operator close_all --yes

# Force paper mode flag
python3 -m safety.operator switch_paper
```

## Routine checks
```bash
python3 -m safety.operator status        # mode, safety state, open positions, equity
python3 -m safety.config_guard           # is it safe to trade? why/why not
python3 -m safety.kill_switch status     # halt + pause state
python3 -m safety.trade_journal          # last 20 audit events
python3 -m lab.data_quality              # price-data integrity gate
python3 rebuild.py                       # full deterministic research rebuild (gated)
```

## Reconstruct any trade (audit trail)
```bash
python3 -m safety.trade_journal <client_order_id>
# -> idea -> risk_decision -> order -> fill -> exit, each with code version + timestamp
```

## Incident response
1. **Unexpected loss / weird fills** → `operator kill`, then `operator status`, then read
   `reports/journal/trade_journal.jsonl` and `reports/logs/`.
2. **Data looks wrong** → `python3 -m lab.data_quality`; if it FAILS, do not trade — the
   rebuild pipeline halts on data integrity failure by design.
3. **Broker disconnected / order errors** → check `reports/alpaca-mirror.json` and
   `/dev/shm/tb-broker.log`. Orders are idempotent (client_order_id), so safe to re-run
   after fixing.
4. **Circuit breaker tripped** → `reports/circuit-breakers.json` shows the reason; sizing
   scalar 0 means new entries are halted for the day. This is automatic and correct.

## Pre-paper-trading checklist
- [ ] `python3 -m pytest -q` all green (core + rigor + safety)
- [ ] `python3 -m lab.validate` — no-look-ahead proof passes
- [ ] `python3 -m safety.config_guard` — safe_to_trade true in paper
- [ ] Broker keys are **paper** keys; withdrawals disabled on the broker account
- [ ] Kill switch tested (`operator kill` then confirm an order is blocked)

## Pre-live-trading checklist (do NOT skip)
- [ ] 30–90 days of paper trading with reconciliation matching
- [ ] Kill switch + circuit breakers tested under load
- [ ] `TB_ALLOW_LIVE=1` set deliberately; live keys least-privilege (trade-only, no withdrawal)
- [ ] Human-approval flow tested (`TB_HUMAN_APPROVED`)
- [ ] Alerts wired for: daily-loss breach, drawdown breach, stale data, broker disconnect
- [ ] Daily report generated and reviewed
