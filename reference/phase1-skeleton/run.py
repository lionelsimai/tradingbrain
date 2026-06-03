#!/usr/bin/env python3
"""Entry point.  Run:  python run.py"""
from agent.data import simulate_prices
from agent.backtest import backtest


def main():
    prices = simulate_prices(days=200)     # [HOOK 1] swap for real data
    r = backtest(prices)
    print("=" * 56)
    print("  PAPER-TRADING AGENT — backtest on SIMULATED data")
    print("  (no real money; these numbers are illustrative only)")
    print("=" * 56)
    for k in ("start_equity", "final_equity", "strategy_return_pct",
              "buy_and_hold_pct", "trades", "win_rate_pct", "max_drawdown_pct"):
        print(f"  {k:<20}: {r[k]}")
    print("  Full decision log saved to:", r["log_file"])


if __name__ == "__main__":
    main()
