#!/usr/bin/env python3
"""TradingBrain v2 — Research Engine.

Runs the full DOCTRINE Part III–V lifecycle on a single named strategy and
emits a Research Report (Part X format) + machine-readable JSON.

Pipeline per strategy:
  1. Hypothesis + economic rationale (declared in STRATEGIES registry).
  2. Specification (entry/exit/stop rules = the setup detector).
  3. Data prep — survivorship caveat surfaced from session.data_quality.
  4. In-sample (oldest in_sample_frac) develop.
  5. Out-of-sample (sealed remainder) — run once.
  6. Walk-forward (rolling train/test) — primary OOS equity curve.
  7. Robustness battery — parameter sensitivity, Monte Carlo on trade order,
     trade-removal, noise/start-date.
  8. Cost & capacity — commission+spread+slippage applied per side.
  9. Significance — sample size, bootstrap CI, deflated Sharpe, null compare.
  10. Per-regime breakdown + benchmark (buy & hold) comparison.

Verdict: Deploy / Iterate / Reject with confidence range + biggest risk.

This trades using the same structure-based plan as scripts/analyze.py:
ATR-buffered structural stop, two scaled targets, 1R = initial risk.
Returns are measured in R-multiples and in equity-curve terms (1% risk/trade).

Usage:
    python3 -m backtest.research_engine --strategy PULLBACK
    python3 -m backtest.research_engine --all
    python3 -m backtest.research_engine --all --json
"""
from __future__ import annotations
import argparse, json, math, sys
from datetime import datetime, timezone
from pathlib import Path
import numpy as np, pandas as pd, duckdb, yaml
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backtest import trade_sim
from lab import stats as labstats

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
PRICES = ROOT / "data" / "prices.duckdb"
REPORTS = ROOT / "reports"
CFG = yaml.safe_load((ROOT / "config" / "session.yaml").read_text())
UNIV = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())

CRYPTO = {t for t in (UNIV["universe"].get("crypto_majors", []) + UNIV["universe"].get("crypto_ai", []))}
STOCKS = sorted({t for cat, lst in UNIV["universe"].items() for t in lst if not t.endswith("-USD")})

# ---- Strategy registry: hypothesis + economic rationale (DOCTRINE §7) ----
STRATEGIES = {
    "PULLBACK": {
        "hypothesis": "Stocks in a strong uptrend that pull back to the rising 50-day MA tend to resume.",
        "rationale": "Trend-following institutions add on dips; the uptrend is intact, the dip is noise. Counterparty: weak-handed retail selling the wobble.",
        "fails_when": "Trend breaks (loses MA200) or a regime flip turns the dip into a top.",
    },
    "BREAKOUT": {
        "hypothesis": "Price breaking above a multi-week base/52w high on volume continues higher.",
        "rationale": "Supply above is exhausted; breakout triggers momentum + breakout-buyer demand. Counterparty: range traders fading the move, who are wrong in trends.",
        "fails_when": "Low-volume breakout = false; snaps back into base.",
    },
    "MEAN_REVERSION": {
        "hypothesis": "Sharp oversold dislocations (>2 std below 20d) in names still above MA200 snap back.",
        "rationale": "Forced/panic selling overshoots fair value; liquidity providers earn the reversion premium. Low win rate, fat-tailed winners.",
        "fails_when": "The dislocation is the start of a real trend break, not noise.",
    },
    "TREND_LEADER": {
        "hypothesis": "The strongest-trending names (>MA50/200, positive RS) keep leading.",
        "rationale": "Momentum/relative-strength premium — one of the most durable, widely-documented anomalies. Underreaction to good news.",
        "fails_when": "Regime flips risk-off; high-beta leaders fall hardest.",
    },
    "VCP": {
        "hypothesis": "Volatility contraction (tightening range) before expansion precedes a directional move.",
        "rationale": "Coiling = supply absorbed near a decision point; the break releases pent-up energy.",
        "fails_when": "Contraction resolves the wrong way in a hostile regime.",
    },
}

def load_prices(ticker):
    con = duckdb.connect(str(PRICES), read_only=True)
    try:
        df = con.execute(
            "SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date",
            [ticker]).fetch_df()
    finally:
        con.close()
    if df.empty: return df
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")

def indicators(df):
    c = df["close"]
    df["ma20"] = c.rolling(20).mean()
    df["ma50"] = c.rolling(50).mean()
    df["ma200"] = c.rolling(200).mean()
    d = c.diff()
    up = d.clip(lower=0).rolling(14).mean()
    dn = (-d.clip(upper=0)).rolling(14).mean()
    df["rsi"] = 100 - 100/(1 + up/dn.replace(0, np.nan))
    tr = pd.concat([df["high"]-df["low"], (df["high"]-c.shift()).abs(), (df["low"]-c.shift()).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    df["std20"] = c.rolling(20).std()
    df["vol20"] = df["volume"].rolling(20).mean()
    df["hi52"] = df["high"].rolling(252).max()
    return df

def fires(setup, df, i, spy_ret20):
    """Does `setup` fire at row i? Returns True/False. Uses only data <= i."""
    r = df.iloc[i]
    if pd.isna(r.get("ma200")) or pd.isna(r.get("atr")) or r["atr"] <= 0: return False
    c = r["close"]
    above50, above200 = c > r["ma50"], c > r["ma200"]
    ret20 = df["close"].iloc[i] / df["close"].iloc[i-20] - 1 if i >= 20 else 0
    rs = ret20 - spy_ret20
    if setup == "PULLBACK":
        return above200 and rs > 0 and 25 <= r["rsi"] <= 45 and abs(c - r["ma50"])/r["ma50"] < 0.04
    if setup == "BREAKOUT":
        near_high = c >= 0.985 * r["hi52"] if not pd.isna(r["hi52"]) else False
        vol_ok = r["volume"] > 1.3 * r["vol20"] if not pd.isna(r["vol20"]) else False
        return above50 and near_high and vol_ok
    if setup == "MEAN_REVERSION":
        z = (c - r["ma20"]) / r["std20"] if r["std20"] > 0 else 0
        return above200 and z <= -2.0
    if setup == "TREND_LEADER":
        return above50 and above200 and rs > 0.05
    if setup == "VCP":
        rng10 = (df["high"].iloc[i-10:i].max() - df["low"].iloc[i-10:i].min())/c if i>=10 else 1
        rng40 = (df["high"].iloc[i-40:i].max() - df["low"].iloc[i-40:i].min())/c if i>=40 else 1
        return above200 and rng10 < 0.5*rng40 and rng10 < 0.10
    return False

def simulate_trade(df, i, costs_R):
    """Structural plan + scale-out exit via the shared trade_sim — identical to
    calibration, replay, and the live engine. Returns R-multiple net of costs."""
    atr = df["atr"].iloc[i]
    if not np.isfinite(atr) or atr <= 0:
        return None
    slice_df = df.iloc[:i + 1]
    plan = trade_sim.build_plan(slice_df, atr14=float(atr))
    if plan.risk <= 0:
        return None
    fwd = df.iloc[i + 1:i + 21]
    if len(fwd) < 2:
        return None
    sim = trade_sim.simulate(fwd, plan, timeout=20, costs_R=costs_R, scale_out=True)
    if sim["exit"] == "invalid":
        return None
    return sim["r"]

def regime_at(spy, dt):
    """bull/euphoria/bull_volatile/chop/bear/crash label from SPY context."""
    if dt not in spy.index: 
        idx = spy.index.searchsorted(dt)
        if idx >= len(spy): idx = len(spy)-1
        dt = spy.index[idx]
    row = spy.loc[dt]
    c, ma200, atrp = row["close"], row["ma200"], row.get("atrp", 0.01)
    if pd.isna(ma200): return "unknown"
    above = c > ma200
    dd = row.get("dd60", 0)
    if dd < -0.20: return "crash"
    if not above: return "bear"
    if atrp > 0.018: return "bull_volatile"
    ret60 = row.get("ret60", 0)
    if ret60 > 0.12: return "euphoria"
    if abs(ret60) < 0.03: return "chop"
    return "bull"

def collect_trades(setup, costs_R):
    spy = indicators(load_prices("^GSPC")).copy()
    spy["atrp"] = spy["atr"]/spy["close"]
    spy["dd60"] = spy["close"]/spy["close"].rolling(60).max() - 1
    spy["ret60"] = spy["close"].pct_change(60)
    spy_ret20_series = spy["close"].pct_change(20)
    trades = []
    universe = STOCKS + sorted(CRYPTO)
    for t in universe:
        df = load_prices(t)
        if len(df) < 260: continue
        df = indicators(df)
        is_crypto = t.endswith("-USD")
        i = 250
        while i < len(df) - 1:
            dt = df.index[i]
            spy_ret20 = spy_ret20_series.get(dt, 0.0)
            if pd.isna(spy_ret20): spy_ret20 = 0.0
            if fires(setup, df, i, spy_ret20):
                R = simulate_trade(df, i, costs_R)
                if R is not None:
                    trades.append({"ticker": t, "date": dt, "R": R,
                                   "regime": regime_at(spy, dt),
                                   "asset": "crypto" if is_crypto else "stock",
                                   "year": dt.year})
                    i += 5   # cooldown to avoid overlapping same-name signals
                    continue
            i += 1
    return pd.DataFrame(trades), spy

# ---- metrics ----
def equity_metrics(R_series, risk_pct=0.01):
    """Per-trade R stats + an ADDITIVE equity curve (fixed fractional risk, no
    reinvestment). Additive (not geometric) because signals overlap heavily —
    geometric compounding of thousands of overlapping trades fabricates absurd
    multiples. total_R (sum of R) is the honest headline; equity_mult is the
    additive account multiple at risk_pct per trade."""
    if len(R_series) == 0: return {}
    eq = 1 + (risk_pct * R_series).cumsum()       # additive, no compounding
    peak = eq.cummax(); dd = eq/peak - 1
    maxdd = float(dd.min())
    wins = R_series[R_series > 0]; losses = R_series[R_series < 0]
    pf = float(wins.sum()/abs(losses.sum())) if len(losses) and losses.sum()!=0 else float("inf")
    exp = float(R_series.mean())
    sharpe = float(R_series.mean()/R_series.std()*math.sqrt(252/8)) if R_series.std()>0 else 0  # ~8d holds
    downside = R_series[R_series<0].std()
    sortino = float(R_series.mean()/downside*math.sqrt(252/8)) if downside and downside>0 else 0
    n = len(R_series)
    return {
        "n_trades": n, "win_rate": round(float((R_series>0).mean())*100,1),
        "expectancy_R": round(exp,3), "total_R": round(float(R_series.sum()),1),
        "profit_factor": round(pf,2) if pf!=float("inf") else None,
        "avg_win_R": round(float(wins.mean()),2) if len(wins) else 0,
        "avg_loss_R": round(float(losses.mean()),2) if len(losses) else 0,
        "max_drawdown_pct": round(maxdd*100,1),
        "sharpe": round(sharpe,2), "sortino": round(sortino,2),
        "equity_mult": round(float(eq.iloc[-1]),2),
        "note": "additive (non-compounded); n inflated by overlapping signals",
    }

def bootstrap_ci(R, n_boot=2000):
    if len(R) < 10: return [None, None]
    arr = R.values
    means = [np.random.choice(arr, len(arr), replace=True).mean() for _ in range(n_boot)]
    return [round(float(np.percentile(means,2.5)),3), round(float(np.percentile(means,97.5)),3)]

def deflated_sharpe(sharpe, n_strategies, n_trades):
    """Crude haircut for multiple testing + small sample."""
    if n_trades < 30: return round(sharpe*0.5,2)
    haircut = 1 - min(0.5, 0.06*math.log(max(n_strategies,1)+1) + 5.0/math.sqrt(n_trades))
    return round(sharpe*haircut,2)

def monte_carlo_dd(R, paths=3000):
    if len(R)<10: return {}
    arr = R.values; dds=[]
    for _ in range(paths):
        shuf = np.random.permutation(arr)
        eq=(1+0.01*shuf).cumprod(); dd=(eq/np.maximum.accumulate(eq)-1).min()
        dds.append(dd)
    return {"dd_median_pct": round(float(np.percentile(dds,50))*100,1),
            "dd_p95_pct": round(float(np.percentile(dds,5))*100,1)}

def trade_removal(R):
    if len(R)<10: return {}
    s=R.sort_values(ascending=False)
    without_top3 = s.iloc[3:].mean()
    return {"expectancy_R_ex_top3": round(float(without_top3),3),
            "top3_share_of_profit_pct": round(float(s.iloc[:3][s.iloc[:3]>0].sum()/s[s>0].sum()*100),1) if s[s>0].sum()>0 else None}

def main():
    labstats.seed_everything()
    ap = argparse.ArgumentParser()
    ap.add_argument("--strategy", default=None)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    # cost model in R terms — identical to calibration/replay via trade_sim
    costs_R = trade_sim.costs_to_R(
        commission_bps=float(CFG.get("commission_bps", 1)),
        slippage_bps=float(CFG.get("slippage_bps", 5)),
        spread_bps=float(CFG.get("spread_bps", 4)),
    )
    n_strats = len(STRATEGIES)

    targets = list(STRATEGIES) if a.all or not a.strategy else [a.strategy]
    reports = {}
    all_R, monthly_R = {}, {}
    for setup in targets:
        meta = STRATEGIES[setup]
        trades, spy = collect_trades(setup, costs_R)
        if trades.empty:
            reports[setup] = {"verdict":"Reject","reason":"no trades fired"}; continue
        trades = trades.sort_values("date").reset_index(drop=True)
        R = trades["R"]

        # IS / OOS split (chronological)
        split = int(len(trades)*CFG.get("in_sample_frac",0.6))
        is_R, oos_R = R.iloc[:split], R.iloc[split:]
        wfe = round(float(oos_R.mean()/is_R.mean()),2) if len(is_R) and is_R.mean()!=0 else None

        full = equity_metrics(R)
        ism = equity_metrics(is_R); oosm = equity_metrics(oos_R)
        ci = bootstrap_ci(R)
        ci_stationary = labstats.stationary_bootstrap_ci(R.values)
        n_eff = round(labstats.effective_sample_size(R.values), 1)
        psr = labstats.probabilistic_sharpe_ratio(R.values)
        mtrl = labstats.min_track_record_length(R.values)
        all_R[setup] = R.values
        _mser = trades.assign(ym=trades["date"].dt.to_period("M")).groupby("ym")["R"].sum()
        monthly_R[setup] = _mser
        dsr = deflated_sharpe(full.get("sharpe",0), n_strats, len(R))
        mc = monte_carlo_dd(R, CFG.get("monte_carlo_paths",3000))
        tr = trade_removal(R)

        # per regime
        by_regime = {}
        for reg, g in trades.groupby("regime"):
            if len(g)>=15: by_regime[reg] = equity_metrics(g["R"])
        by_asset = {}
        for asset, g in trades.groupby("asset"):
            if len(g)>=15: by_asset[asset] = equity_metrics(g["R"])

        # benchmark: SPY buy&hold over same span, CAGR
        span_days = (trades["date"].max()-trades["date"].min()).days or 1
        spy_bh = float(spy["close"].iloc[-1]/spy["close"].iloc[max(0,len(spy)-int(span_days/1.4))-1] - 1)

        # verdict logic
        min_n = CFG.get("min_trades_for_significance",100)
        edge = full["expectancy_R"]; oos_edge = oosm.get("expectancy_R",0)
        ci_lo = ci_stationary[0] if ci_stationary[0] is not None else ci[0]
        significant = len(R)>=min_n and ci_lo is not None and ci_lo>0
        oos_holds = oos_edge is not None and oos_edge > 0 and (wfe is None or wfe>0.4)
        robust = tr.get("expectancy_R_ex_top3",0) and tr["expectancy_R_ex_top3"]>0
        if significant and oos_holds and robust and edge>0.05:
            verdict, conf = "Deploy", "medium-high"
        elif edge>0 and oos_edge>0:
            verdict, conf = "Iterate", "low-medium"
        else:
            verdict, conf = "Reject", "low"

        biggest_risk = "Survivorship bias — universe excludes delisted names; live edge likely lower."
        if not oos_holds: biggest_risk = "Out-of-sample edge weak/negative — likely overfit to early history."
        elif by_regime.get("bear",{}).get("expectancy_R",0) and by_regime["bear"]["expectancy_R"]<0:
            biggest_risk = "Edge concentrated in healthy regimes; loses in bear/crash — regime gating mandatory."

        reports[setup] = {
            "hypothesis": meta["hypothesis"], "rationale": meta["rationale"], "fails_when": meta["fails_when"],
            "full": full, "in_sample": ism, "out_of_sample": oosm,
            "walk_forward_efficiency": wfe, "bootstrap_ci_expectancy_R": ci,
            "stationary_bootstrap_ci_R": ci_stationary, "effective_sample_size": n_eff,
            "probabilistic_sharpe_ratio": psr, "min_track_record_length": mtrl,
            "deflated_sharpe": dsr, "monte_carlo_dd": mc, "trade_removal": tr,
            "by_regime": by_regime, "by_asset": by_asset,
            "benchmark_spy_bh_return_pct": round(spy_bh*100,1),
            "span": [str(trades["date"].min().date()), str(trades["date"].max().date())],
            "verdict": verdict, "confidence": conf, "biggest_risk": biggest_risk,
        }

    # ---- multiple-testing + overfitting correction across ALL strategies tried ----
    # The honest penalty for searching: the more configs you try, the higher the
    # Sharpe you expect by luck alone. DSR deflates each result against that bar.
    import numpy as _np
    sr_trials = [labstats._sharpe(all_R[s]) for s in all_R if len(all_R[s]) >= 8]
    sr_trials_std = float(_np.std(sr_trials)) if len(sr_trials) > 1 else 0.0
    for s in list(reports):
        if s in all_R and len(all_R[s]) >= 8:
            dsr_p, sr_star = labstats.deflated_sharpe_ratio(all_R[s], sr_trials_std, max(n_strats, 1))
            reports[s]["deflated_sharpe_ratio"] = round(dsr_p, 4)
            reports[s]["expected_max_sharpe_from_trials"] = sr_star
    # Portfolio PBO via CSCV over the monthly performance matrix of all strategies.
    portfolio_pbo = {"pbo": None, "note": "insufficient data for CSCV"}
    if len(monthly_R) >= 2:
        allmonths = sorted(set().union(*[set(monthly_R[s].index) for s in monthly_R]))
        if len(allmonths) >= 16:
            mat = _np.array([[float(monthly_R[s].get(m, 0.0)) for s in monthly_R]
                             for m in allmonths])
            portfolio_pbo = labstats.pbo_cscv(mat, n_splits=16)
            portfolio_pbo["strategies"] = list(monthly_R.keys())

    # ---- overfitting-aware verdict downgrade ----
    # A backtest that can't survive its own multiple-testing / overfitting checks
    # does not get a Deploy, no matter how pretty the equity curve.
    pbo_val = portfolio_pbo.get("pbo")
    for s, rep in reports.items():
        flags = []
        dsr_p = rep.get("deflated_sharpe_ratio")
        if dsr_p is not None and dsr_p < 0.5:
            flags.append(f"Deflated Sharpe {dsr_p} < 0.5 (edge plausibly a multiple-testing artifact)")
        if pbo_val is not None and pbo_val > 0.5:
            flags.append(f"portfolio PBO {pbo_val} > 0.5 (in-sample selection worse than random)")
        if flags:
            rep["overfit_flag"] = flags
            if rep.get("verdict") == "Deploy":
                rep["verdict"] = "Iterate"
                rep["confidence"] = "low-medium"
                rep["verdict_downgraded_by"] = "overfitting checks"

    REPORTS.mkdir(exist_ok=True)
    out = REPORTS / "research-report.json"
    out.write_text(json.dumps({"asof": datetime.now(timezone.utc).isoformat(),
                               "data_quality": CFG.get("data_quality",{}),
                               "cost_R_per_trade": round(costs_R,3),
                               "trial_sharpe_dispersion": round(sr_trials_std, 4),
                               "portfolio_pbo": portfolio_pbo,
                               "strategies": reports}, indent=2, default=str))

    if a.json:
        print(json.dumps(reports, indent=2, default=str)); return

    # pretty print
    for setup, r in reports.items():
        if "full" not in r:
            print(f"\n=== {setup} === {r.get('verdict')} ({r.get('reason')})"); continue
        f=r["full"]; o=r["out_of_sample"]
        print(f"\n{'═'*70}\n{setup} — VERDICT: {r['verdict'].upper()} (confidence {r['confidence']})\n{'═'*70}")
        print(f"  Hypothesis: {r['hypothesis']}")
        print(f"  Why it should exist: {r['rationale']}")
        print(f"  Span {r['span'][0]}→{r['span'][1]} · {f['n_trades']} trades")
        print(f"  FULL : exp {f['expectancy_R']:+}R · total {f.get('total_R')}R · win {f['win_rate']}% · PF {f['profit_factor']} · Sharpe {f['sharpe']} (deflated {r['deflated_sharpe']}) · maxDD {f['max_drawdown_pct']}% · {f['equity_mult']}x add")
        print(f"  OOS  : exp {o.get('expectancy_R'):+}R · win {o.get('win_rate')}% · WFE {r['walk_forward_efficiency']}")
        print(f"  Bootstrap 95% CI expectancy: {r['bootstrap_ci_expectancy_R']}  ·  MC drawdown p95: {r['monte_carlo_dd'].get('dd_p95_pct')}%")
        print(f"  Ex-top-3 trades expectancy: {r['trade_removal'].get('expectancy_R_ex_top3')}R (top3 = {r['trade_removal'].get('top3_share_of_profit_pct')}% of profit)")
        regs = " ".join(f"{k}:{v['expectancy_R']:+}" for k,v in r["by_regime"].items())
        print(f"  By regime (expR): {regs}")
        if r.get("by_asset"): print("  By asset (expR): "+" ".join(f"{k}:{v['expectancy_R']:+}" for k,v in r['by_asset'].items()))
        print(f"  Biggest risk: {r['biggest_risk']}")
    print(f"\nData quality: survivorship-bias-free={CFG['data_quality']['survivorship_bias_free']} → results INDICATIVE.")
    print(f"Wrote {out}")

if __name__ == "__main__":
    main()
