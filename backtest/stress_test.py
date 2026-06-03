#!/usr/bin/env python3
"""Ultimate stress test + calibration over full history.

For every setup the swing engine can fire, this:
  1. Walks each ticker's full history (no look-ahead; signals from data <= T).
  2. Simulates the FULL trade plan via the shared trade_sim (structure-based
     stop + two targets, 50% scale at T1, breakeven runner) — the SAME plan
     and exit the live engine and the replay scorecard use.
  3. Records realized R-multiple (net of costs), win/loss, hold days,
     regime-at-entry, and asset class.
  4. Aggregates by setup, setup x regime, asset class, and crash window.
  5. Runs walk-forward (70/30) to flag overfit setups (OOS << IS).
  6. Writes reports/calibration.json — per-setup expectancy, win rate,
     profit factor, regime multipliers, and an ENABLE/DISABLE verdict.

Detection uses scripts.signals.swing_setup (compute_features + detect_at), so
calibration measures EXACTLY what the live detector fires. Plan + exit + costs
come from backtest.trade_sim, identical to research, replay, and live.
"""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path
import duckdb, numpy as np, pandas as pd, yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.signals.swing_setup import compute_features, detect_at
from backtest import trade_sim
from lab import stats as labstats

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
SESSION = ROOT / "config" / "session.yaml"
REPORTS = ROOT / "reports"
REPORTS.mkdir(exist_ok=True)

CRYPTO_SUFFIX = "-USD"
STRESS_WINDOWS = {
    "2018_Q4_selloff": ("2018-10-01", "2018-12-31"),
    "2020_covid_crash": ("2020-02-15", "2020-04-15"),
    "2022_bear":        ("2022-01-01", "2022-10-31"),
    "2025_tariff_vol":  ("2025-01-01", "2025-06-30"),
}
STEP = 3                    # sample a decision point every N bars
TIMEOUT_DAYS = 20
MIN_OOS_EXPECTANCY = 0.05   # min avg R (net) to keep a setup enabled
MIN_OOS_N = 30


def costs_R() -> float:
    cfg = yaml.safe_load(SESSION.read_text()) if SESSION.exists() else {}
    return trade_sim.costs_to_R(
        commission_bps=float(cfg.get("commission_bps", 1)),
        slippage_bps=float(cfg.get("slippage_bps", 5)),
        spread_bps=float(cfg.get("spread_bps", 3)),
    )


def regime_series(spy: pd.DataFrame) -> dict:
    """Vectorized regime label per SPY date (point-in-time)."""
    s = spy.sort_values("date").reset_index(drop=True)
    close = s["close"]
    ma200 = close.rolling(200).mean()
    ma50 = close.rolling(50).mean()
    vol20 = close.pct_change().rolling(20).std() * np.sqrt(252)
    out = {}
    cl = close.values; m2 = ma200.values; m5 = ma50.values; v = vol20.values
    dts = pd.to_datetime(s["date"]).values
    for i in range(len(s)):
        if i < 200 or not np.isfinite(m2[i]):
            out[dts[i]] = "unknown"; continue
        if cl[i] > m2[i] and m5[i] > m2[i]:
            out[dts[i]] = "euphoria" if (np.isfinite(v[i]) and v[i] < 0.18) else "bull_volatile"
        elif cl[i] < m2[i] and m5[i] < m2[i]:
            out[dts[i]] = "bear"
        else:
            out[dts[i]] = "chop"
    return out


def regime_lookup(reg_map: dict, sorted_dates: np.ndarray, d) -> str:
    """Nearest prior regime label for date d."""
    idx = np.searchsorted(sorted_dates, np.datetime64(d), side="right") - 1
    if idx < 0:
        return "unknown"
    return reg_map.get(sorted_dates[idx], "unknown")


def agg(trades) -> dict:
    if isinstance(trades, list):
        r = np.array([t["r"] for t in trades]); holds = [t["hold"] for t in trades]
    else:
        r = trades["r"].values; holds = trades["hold"].values
    if len(r) == 0:
        return {}
    wins = r[r > 0]; losses = r[r <= 0]
    gross_win = wins.sum() if len(wins) else 0.0
    gross_loss = -losses.sum() if len(losses) else 0.0
    mcl = cur = 0
    for x in r:
        if x <= 0:
            cur += 1; mcl = max(mcl, cur)
        else:
            cur = 0
    return {
        "n": int(len(r)),
        "win_rate": round(float((r > 0).mean()) * 100, 1),
        "expectancy_R": round(float(r.mean()), 3),
        "median_R": round(float(np.median(r)), 3),
        "avg_win_R": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_R": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "profit_factor": round(float(gross_win / gross_loss), 2) if gross_loss > 0 else float("inf"),
        "max_consec_losses": int(mcl),
        "total_R": round(float(r.sum()), 1),
        "avg_hold_days": round(float(np.mean(holds)), 1),
    }


def main():
    labstats.seed_everything()
    cR = costs_R()
    con = duckdb.connect(str(PRICES), read_only=True)
    tickers = [r[0] for r in con.execute(
        "SELECT DISTINCT ticker FROM prices WHERE ticker NOT IN ('SPY','QQQ','SMH')").fetchall()]
    spy = con.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker='SPY' ORDER BY date").fetchdf()
    spy["date"] = pd.to_datetime(spy["date"])
    reg_map = regime_series(spy)
    reg_dates = np.array(sorted(reg_map.keys()))

    all_trades = []
    print(f"Stress-testing {len(tickers)} tickers over full history (costs={cR:.4f}R/trade)...", flush=True)
    for ti, t in enumerate(tickers):
        df = con.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date", [t]).fetchdf()
        if len(df) < 270:
            continue
        df["date"] = pd.to_datetime(df["date"])
        df = df.reset_index(drop=True)
        asset = "crypto" if t.endswith(CRYPTO_SUFFIX) else "stock"
        f = compute_features(df, spy)
        closes = df["close"].values
        dates = df["date"].values
        n = len(df)
        for i in range(251, n - 1, STEP):
            d = detect_at(f, i, clenow_rank=None)
            kind = d.get("setup", "NONE")
            if kind == "NONE":
                continue
            row = f.iloc[i]
            a = float(row["atr14"])
            if not np.isfinite(a) or a <= 0:
                continue
            px = float(closes[i])
            plan = trade_sim.plan_from_levels(
                px, a,
                swing_low_10=float(row["swing_low_10"]), swing_high_20=float(row["swing_high_20"]),
                swing_high_60=float(row["swing_high_60"]), swing_low_20=float(row["swing_low_20"]),
                hi252=float(row["hi252"]),
            )
            fwd = df.iloc[i + 1:i + 1 + TIMEOUT_DAYS]
            if len(fwd) < 2:
                continue
            sim = trade_sim.simulate(fwd, plan, timeout=TIMEOUT_DAYS, costs_R=cR, scale_out=True)
            if sim["exit"] == "invalid":
                continue
            all_trades.append({
                "setup": kind, "regime": regime_lookup(reg_map, reg_dates, dates[i]),
                "asset": asset, "r": sim["r"], "hold": sim["hold"], "exit": sim["exit"],
                "entry_date": str(pd.Timestamp(dates[i]).date()), "ticker": t,
            })
        if (ti + 1) % 15 == 0:
            print(f"  ...{ti+1}/{len(tickers)}  ({len(all_trades)} trades)", flush=True)

    df_tr = pd.DataFrame(all_trades)
    print(f"\nTotal simulated trades: {len(df_tr)}", flush=True)

    by_setup = {k: agg(g) for k, g in df_tr.groupby("setup")}
    by_setup_regime = {}
    for (s, r), g in df_tr.groupby(["setup", "regime"]):
        by_setup_regime.setdefault(s, {})[r] = agg(g)
    by_asset = {k: agg(g) for k, g in df_tr.groupby("asset")}

    stress = {}
    df_tr["entry_dt"] = pd.to_datetime(df_tr["entry_date"])
    for name, (a, b) in STRESS_WINDOWS.items():
        sub = df_tr[(df_tr["entry_dt"] >= a) & (df_tr["entry_dt"] <= b)]
        stress[name] = agg(sub) if len(sub) else {"n": 0}

    cut = df_tr["entry_dt"].quantile(0.70)
    wf = {}
    for s, g in df_tr.groupby("setup"):
        is_ = g[g["entry_dt"] <= cut]; oos = g[g["entry_dt"] > cut]
        wf[s] = {"in_sample": agg(is_), "out_of_sample": agg(oos)}

    calibration = {}
    for s, stats in by_setup.items():
        oos = wf[s]["out_of_sample"]
        oos_exp = oos.get("expectancy_R", 0) if oos else 0
        enabled = bool(oos and oos.get("n", 0) >= MIN_OOS_N and oos_exp >= MIN_OOS_EXPECTANCY)
        base_exp = stats["expectancy_R"] or 0.01
        reg_mult = {}
        for reg, rs in by_setup_regime.get(s, {}).items():
            if rs and rs.get("n", 0) >= 20:
                reg_mult[reg] = round(max(0.0, min(1.5, (rs["expectancy_R"] / base_exp))), 2) if base_exp else 1.0
        calibration[s] = {
            "enabled": enabled,
            "expectancy_R": stats["expectancy_R"],
            "oos_expectancy_R": oos_exp,
            "win_rate": stats["win_rate"],
            "profit_factor": stats["profit_factor"],
            "max_consec_losses": stats["max_consec_losses"],
            "n": stats["n"],
            "regime_multiplier": reg_mult,
            "overfit_flag": bool(oos and stats["expectancy_R"] > 0 and oos_exp < 0.5 * stats["expectancy_R"]),
        }

    out = {
        "asof": date.today().isoformat(),
        "n_trades": int(len(df_tr)),
        "costs_R_per_trade": round(cR, 4),
        "step_bars": STEP,
        "history_span": [str(df_tr["entry_dt"].min().date()) if len(df_tr) else "",
                         str(spy["date"].max().date())],
        "by_setup": by_setup,
        "by_setup_regime": by_setup_regime,
        "by_asset": by_asset,
        "stress_windows": stress,
        "walk_forward": wf,
        "calibration": calibration,
        "min_oos_expectancy_R": MIN_OOS_EXPECTANCY,
        "note": "Net of costs. Detection=swing_setup.detect_at; plan/exit=trade_sim (scale_out). "
                "Overlapping samples (step<hold) inflate n; treat significance accordingly.",
    }
    (REPORTS / "stress-test.json").write_text(json.dumps(out, indent=2, default=str))
    (REPORTS / "calibration.json").write_text(json.dumps({
        "asof": out["asof"], "source": "stress-test.json", "costs_R_per_trade": round(cR, 4),
        "calibration": calibration,
    }, indent=2, default=str))

    print("\n=== BY SETUP (full history, net of costs) ===")
    for s, st in sorted(by_setup.items(), key=lambda x: -(x[1].get("expectancy_R") or 0)):
        print(f"  {s:14} n={st['n']:6}  win {st['win_rate']:5.1f}%  exp {st['expectancy_R']:+.3f}R  "
              f"PF {st['profit_factor']}  maxLossStreak {st['max_consec_losses']}")
    print("\n=== WALK-FORWARD (OOS) ===")
    for s, w in wf.items():
        o = w["out_of_sample"]; i = w["in_sample"]
        if o and i:
            print(f"  {s:14} IS exp {i.get('expectancy_R',0):+.3f}R -> OOS exp {o.get('expectancy_R',0):+.3f}R  (n_oos={o.get('n',0)})")
    print("\n=== STRESS WINDOWS ===")
    for name, st in stress.items():
        if st.get("n", 0) > 0:
            print(f"  {name:20} n={st['n']:4}  win {st.get('win_rate',0):5.1f}%  exp {st.get('expectancy_R',0):+.3f}R")
        else:
            print(f"  {name:20} no trades")
    print("\n=== CALIBRATION VERDICTS ===")
    for s, c in calibration.items():
        flag = "ENABLED " if c["enabled"] else "DISABLED"
        of = " OVERFIT" if c["overfit_flag"] else ""
        print(f"  {s:14} [{flag}]  oos_exp {c['oos_expectancy_R']:+.3f}R{of}")
    print(f"\nWrote {REPORTS/'stress-test.json'} and {REPORTS/'calibration.json'}")


if __name__ == "__main__":
    main()
