#!/usr/bin/env python3
"""Multi-asset backtest engine.

Honest by design:
  - Real risk rails: stop-loss, take-profit, drawdown kill switch
  - Equal-weight position sizing capped by max_position_pct
  - Transaction costs applied on EVERY fill (commission + slippage + half-spread,
    via backtest.costs.BASE) — the engine previously modeled ZERO cost (FIX-3).
  - Marked-to-market at close.
  KNOWN LIMITATION (stated honestly): the rebalance decides on bar T's close and
  fills at that SAME close (optimistic same-bar fill). Next-bar fills are the
  remaining FIX-3 sub-task (needs the price DB to verify end-to-end). Costs are
  the larger correction and are landed here.

Run a strategy by passing a `score_fn(prices_df, date) -> pd.Series` that returns
a ticker -> score series for the given date. Top-N by score gets bought; positions
are sold when score drops below the hold threshold or risk rules trigger.
"""
from __future__ import annotations
import argparse, sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import duckdb, numpy as np, pandas as pd, yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.db import PRICES_DB  # noqa: E402
from backtest.costs import BASE as COST_MODEL  # noqa: E402

# Per-side transaction cost fraction (commission + slippage + half-spread). FIX-3:
# the engine previously applied ZERO cost. A BUY fills above mid, a SELL below it.
_PS = COST_MODEL.per_side_bps() / 10_000.0

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
SOURCES = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text())
RULES = SOURCES["risk_rules"]


def _load_sector_map() -> dict[str, str]:
    """ticker -> category (from universe.yaml) for the sector-exposure cap."""
    try:
        uni = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text()).get("universe", {})
    except Exception:
        return {}
    m = {}
    for cat, tickers in (uni or {}).items():
        for t in (tickers or []):
            m[t] = cat
    return m


_SECTOR = _load_sector_map()


@dataclass
class Position:
    ticker: str
    shares: float
    entry_price: float
    entry_date: date


@dataclass
class BacktestResult:
    start: date
    end: date
    initial_equity: float
    final_equity: float
    return_pct: float
    cagr_pct: float
    sharpe: float
    max_drawdown_pct: float
    trades: int
    win_rate_pct: float
    benchmark_return_pct: float
    halted: bool
    equity_curve: pd.DataFrame
    trade_log: pd.DataFrame


def load_prices(start: date, end: date, tickers: list[str] | None = None) -> pd.DataFrame:
    con = duckdb.connect(str(PRICES_DB), read_only=True)
    if tickers:
        q = "SELECT date, ticker, adj_close FROM prices WHERE date BETWEEN ? AND ? AND ticker IN (" \
            + ",".join("?" * len(tickers)) + ") ORDER BY date, ticker"
        df = con.execute(q, [start, end, *tickers]).fetch_df()
    else:
        df = con.execute(
            "SELECT date, ticker, adj_close FROM prices WHERE date BETWEEN ? AND ? ORDER BY date, ticker",
            [start, end]
        ).fetch_df()
    con.close()
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df.pivot(index="date", columns="ticker", values="adj_close").ffill()


def momentum_score(prices: pd.DataFrame, as_of: date, lookback: int = 90) -> pd.Series:
    """Annualized log slope × R² (Clenow-style)."""
    idx = list(prices.index)
    if as_of not in idx:
        return pd.Series(dtype=float)
    i = idx.index(as_of)
    if i < lookback:
        return pd.Series(dtype=float)
    window = prices.iloc[i - lookback:i + 1]
    scores = {}
    for t in window.columns:
        y = window[t].dropna().values
        if len(y) < lookback - 5:
            continue
        x = np.arange(len(y), dtype=float)
        logy = np.log(np.clip(y, 1e-6, None))
        try:
            slope, intercept = np.polyfit(x, logy, 1)
            pred = slope * x + intercept
            ss_res = float(np.sum((logy - pred) ** 2))
            ss_tot = float(np.sum((logy - logy.mean()) ** 2))
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            ann = (np.exp(slope * 252) - 1) * 100
            scores[t] = ann * r2
        except Exception:
            continue
    return pd.Series(scores)


def regime_ok(prices: pd.DataFrame, as_of: date, benchmark: str = "SPY", ma: int = 200) -> bool:
    if benchmark not in prices.columns:
        return True
    idx = list(prices.index)
    if as_of not in idx:
        return True
    i = idx.index(as_of)
    if i < ma:
        return True
    window = prices[benchmark].iloc[i - ma:i + 1].dropna()
    if window.empty:
        return True
    return float(window.iloc[-1]) > float(window.mean())


def run_backtest(
    start: date,
    end: date,
    score_fn=momentum_score,
    top_n: int = 5,
    rebalance_days: int = 21,
    initial_equity: float = 100_000.0,
    benchmark: str = "SPY",
    regime_filter: bool = True,
    tickers: list[str] | None = None,
) -> BacktestResult:
    prices = load_prices(start - timedelta(days=300), end, tickers)
    if prices.empty:
        raise RuntimeError("No prices loaded.")
    cash = initial_equity
    positions: dict[str, Position] = {}
    peak_eq = initial_equity
    halted = False
    equity_rows = []
    trade_rows = []

    rebalance_counter = 0
    in_window_dates = [d for d in prices.index if d >= start and d <= end]

    for d in in_window_dates:
        today_prices = prices.loc[d].dropna()
        equity = cash + sum(p.shares * today_prices.get(p.ticker, p.entry_price) for p in positions.values())
        peak_eq = max(peak_eq, equity)
        dd = (peak_eq - equity) / peak_eq if peak_eq > 0 else 0
        if dd >= RULES["max_drawdown_halt_pct"]:
            halted = True

        # Protective exits first.
        for t, p in list(positions.items()):
            if t not in today_prices.index:
                continue
            price = float(today_prices[t])
            chg = (price - p.entry_price) / p.entry_price
            reason = None
            if chg <= -RULES["stop_loss_pct"]:
                reason = "STOP"
            elif chg >= RULES["take_profit_pct"]:
                reason = "TAKE"
            if reason:
                fill = price * (1 - _PS)          # sell fills BELOW mid (costs)
                cash += p.shares * fill
                trade_rows.append({
                    "entry_date": p.entry_date, "exit_date": d, "ticker": t, "entry_price": p.entry_price,
                    "exit_price": fill, "shares": p.shares,
                    "pnl_pct": (fill - p.entry_price) / p.entry_price * 100,
                    "reason": reason
                })
                del positions[t]

        # Rebalance window.
        if rebalance_counter == 0:
            allow_new = not halted and (regime_ok(prices, d, benchmark) if regime_filter else True)
            scores = score_fn(prices.loc[:d], d)
            scores = scores.dropna().sort_values(ascending=False)
            target_tickers = list(scores.head(top_n).index) if allow_new else []

            # Exit positions no longer in target.
            for t in list(positions.keys()):
                if t not in target_tickers:
                    if t in today_prices.index:
                        price = float(today_prices[t])
                        p = positions[t]
                        fill = price * (1 - _PS)      # sell fills BELOW mid (costs)
                        cash += p.shares * fill
                        trade_rows.append({
                            "entry_date": p.entry_date, "exit_date": d, "ticker": t, "entry_price": p.entry_price,
                            "exit_price": fill, "shares": p.shares,
                            "pnl_pct": (fill - p.entry_price) / p.entry_price * 100,
                            "reason": "REBAL"
                        })
                        del positions[t]

            # Enter new ones, equal weight.
            new_entries = [t for t in target_tickers if t not in positions and t in today_prices.index]
            if new_entries:
                per_trade = min(equity * RULES["max_position_pct"],
                                cash / max(1, len(new_entries) + 0))
                # Current sector exposure ($) — enforce configured max_sector_pct.
                max_sector = RULES.get("max_sector_pct", 1.0)
                sector_val: dict[str, float] = {}
                for pt, pp in positions.items():
                    sec = _SECTOR.get(pt, pt)
                    sector_val[sec] = sector_val.get(sec, 0.0) + pp.shares * float(today_prices.get(pt, pp.entry_price))
                for t in new_entries:
                    if cash < 100:
                        break
                    mid = float(today_prices[t])
                    if mid <= 0:
                        continue
                    fill = mid * (1 + _PS)           # buy fills ABOVE mid (costs)
                    qty = (per_trade) / fill
                    if qty * fill > cash:
                        qty = cash / fill
                    # Sector cap: don't let any one category exceed max_sector_pct of equity.
                    sec = _SECTOR.get(t, t)
                    if equity > 0 and (sector_val.get(sec, 0.0) + qty * fill) / equity > max_sector:
                        continue
                    cash -= qty * fill
                    positions[t] = Position(ticker=t, shares=qty, entry_price=fill, entry_date=d)
                    sector_val[sec] = sector_val.get(sec, 0.0) + qty * fill
        rebalance_counter = (rebalance_counter + 1) % rebalance_days

        equity_rows.append({"date": d, "equity": equity, "cash": cash, "n_positions": len(positions)})

    # Final mark-to-market
    final_prices = prices.loc[in_window_dates[-1]].dropna() if in_window_dates else None
    final_eq = cash + sum(p.shares * float(final_prices.get(p.ticker, p.entry_price)) for p in positions.values()) if final_prices is not None else cash
    eq_df = pd.DataFrame(equity_rows)
    eq_df["return"] = eq_df["equity"].pct_change().fillna(0)
    eq_df["dd"] = 1 - eq_df["equity"] / eq_df["equity"].cummax()

    n_years = max((end - start).days / 365.25, 0.1)
    return_pct = (final_eq / initial_equity - 1) * 100
    cagr = ((final_eq / initial_equity) ** (1 / n_years) - 1) * 100
    sharpe = float(eq_df["return"].mean() / eq_df["return"].std() * np.sqrt(252)) if eq_df["return"].std() > 0 else 0
    max_dd = float(eq_df["dd"].max() * 100)

    bench_start = prices[benchmark].loc[in_window_dates[0]] if benchmark in prices.columns else None
    bench_end = prices[benchmark].loc[in_window_dates[-1]] if benchmark in prices.columns else None
    bench_return = ((bench_end / bench_start - 1) * 100) if bench_start and bench_end else 0.0

    trade_df = pd.DataFrame(trade_rows)
    trades = len(trade_df)
    win_rate = float((trade_df["pnl_pct"] > 0).mean() * 100) if trades else 0

    return BacktestResult(
        start=start, end=end,
        initial_equity=initial_equity, final_equity=final_eq,
        return_pct=round(return_pct, 2), cagr_pct=round(cagr, 2),
        sharpe=round(sharpe, 2), max_drawdown_pct=round(max_dd, 1),
        trades=trades, win_rate_pct=round(win_rate, 1),
        benchmark_return_pct=round(bench_return, 2),
        halted=halted, equity_curve=eq_df, trade_log=trade_df,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=str(date.today() - timedelta(days=365 * 2)))
    ap.add_argument("--end", default=str(date.today() - timedelta(days=1)))
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--rebalance", type=int, default=21)
    ap.add_argument("--no-regime", action="store_true")
    args = ap.parse_args()

    r = run_backtest(
        start=date.fromisoformat(args.start),
        end=date.fromisoformat(args.end),
        top_n=args.top,
        rebalance_days=args.rebalance,
        regime_filter=not args.no_regime,
    )
    print(f"\nBacktest {r.start} → {r.end}")
    print(f"  Strategy:  {r.return_pct:+.2f}%   CAGR {r.cagr_pct:+.2f}%   Sharpe {r.sharpe:.2f}   MaxDD {r.max_drawdown_pct:.1f}%")
    print(f"  Benchmark: {r.benchmark_return_pct:+.2f}%  (SPY)")
    print(f"  Alpha:     {r.return_pct - r.benchmark_return_pct:+.2f}%")
    print(f"  Trades:    {r.trades}   Win rate {r.win_rate_pct:.1f}%   Halted: {r.halted}")
    out = ROOT / "reports" / f"backtest-{r.start}-to-{r.end}.csv"
    r.equity_curve.to_csv(out, index=False)
    print(f"  Equity curve → {out}")


if __name__ == "__main__":
    main()
