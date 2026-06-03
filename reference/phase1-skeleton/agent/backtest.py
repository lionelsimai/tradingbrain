"""Verifiability: run the agent over history and report a scorecard."""
from config import CFG
from agent.brain import Decision, decide
from agent.broker import Portfolio, execute, risk_check
from agent.observability import DecisionLog


def backtest(prices) -> dict:
    p = Portfolio(cash=CFG.starting_cash)
    log = DecisionLog()
    initial = CFG.starting_cash
    peak = initial
    max_dd = 0.0
    trades = wins = 0
    halted = False

    for day in range(30, len(prices)):            # warm up the indicators first
        history = prices[: day + 1]
        price = history[-1]
        equity = p.value(price)

        peak = max(peak, equity)
        dd = (peak - equity) / peak
        max_dd = max(max_dd, dd)
        if dd >= CFG.max_drawdown_halt_pct:
            halted = True                          # KILL SWITCH latches on

        # protective exits always run, even when halted
        forced = risk_check(p, price)
        if forced and p.shares > 0:
            pnl = (price - p.entry_price) * p.shares
            trades += 1
            wins += 1 if pnl > 0 else 0
            log.record(Decision(day, price, {}, 0.0, "SELL", forced), p.value(price))
            p.cash += p.shares * price
            p.shares = 0
            p.entry_price = 0.0
            continue

        d = decide(day, history, p.shares)
        if halted and d.action == "BUY":
            d = Decision(day, price, d.signals, d.confidence, "HOLD",
                         f"KILL SWITCH active (drawdown {dd:.0%}) — no new entries.")
        if d.action == "SELL" and p.shares > 0:
            pnl = (price - p.entry_price) * p.shares
            trades += 1
            wins += 1 if pnl > 0 else 0
        execute(p, d)
        log.record(d, p.value(price))

    final = p.value(prices[-1])
    path = log.save()
    return {
        "start_equity": round(initial, 2),
        "final_equity": round(final, 2),
        "strategy_return_pct": round((final / initial - 1) * 100, 2),
        "buy_and_hold_pct": round((prices[-1] / prices[30] - 1) * 100, 2),
        "trades": trades,
        "win_rate_pct": round(100 * wins / trades, 1) if trades else 0.0,
        "max_drawdown_pct": round(max_dd * 100, 1),
        "log_file": path,
    }
