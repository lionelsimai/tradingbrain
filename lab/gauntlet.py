#!/usr/bin/env python3
"""TradingBrain — Validation Gauntlet (institutional checks + verdict).

Implements the advanced, "hostile quant desk" checks from the Pro validation
spec that did not exist yet, and rolls them into a 0-100 robustness scorecard
with an APPROVED / CONDITIONAL / REJECTED verdict:

  * PBO   — Probability of Backtest Overfitting via combinatorially symmetric
            cross-validation across the setups (Phase C).
  * DSR   — Deflated Sharpe Ratio, penalizing the number of trials and the
            (short) track length (Phase C).
  * Skill vs beta — regress strategy returns on the market; compare win rate to a
            matched-horizon random-long benchmark (Phase C2).
  * Break-even cost — the cost level at which the edge dies, and the headroom (E).
  * Capacity — a rough capital ceiling from average dollar volume (E).
  * Fractional Kelly — is the risk-per-trade safely below the Kelly ceiling (§4).
  * Pulls risk-of-ruin / regime / overfitting-gap from the existing reports.

Everything is computed on the REAL resolved ledger and labeled honestly. The
ledger currently covers only ~8 months and is REPLAY (survivorship-biased), so
several scores are deliberately low and the verdict will not be APPROVED.

CLI:
  python3 -m lab.gauntlet            # scorecard + verdict, writes reports/gauntlet.json
  python3 -m lab.gauntlet --json
"""
from __future__ import annotations
import json, math, sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT

KB = ROOT / "data" / "knowledge.duckdb"
PRICES = ROOT / "data" / "prices.duckdb"
REPORTS = ROOT / "reports"
EULER = 0.5772156649
Z = NormalDist().inv_cdf
PHI = NormalDist().cdf


def _report(name, default=None):
    try:
        return json.loads((REPORTS / name).read_text())
    except Exception:
        return default if default is not None else {}


def _ledger() -> pd.DataFrame:
    import duckdb
    c = duckdb.connect(str(KB), read_only=True)
    try:
        df = c.execute(
            "SELECT emit_date, setup, regime, realized_R, hold_days FROM signal_ledger "
            "WHERE realized_R IS NOT NULL").fetchdf()
    finally:
        c.close()
    df["emit_date"] = pd.to_datetime(df["emit_date"])
    return df


def _spy_returns() -> pd.Series:
    import duckdb
    c = duckdb.connect(str(PRICES), read_only=True)
    try:
        df = c.execute("SELECT date, adj_close FROM prices WHERE ticker='SPY' ORDER BY date").fetchdf()
    finally:
        c.close()
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["adj_close"].pct_change().dropna()


def _sharpe(x: np.ndarray) -> float:
    s = x.std(ddof=1)
    return float(x.mean() / s) if s > 0 else 0.0


# ---------------------------------------------------------------- Phase C: PBO
def pbo(df: pd.DataFrame, n_blocks: int = 8) -> dict:
    """Combinatorially symmetric cross-validation across setups. Estimates the
    probability that the setup that looks best in-sample is below-median
    out-of-sample. High PBO => the 'best' choice is likely luck."""
    setups = [s for s, n in df["setup"].value_counts().items() if n >= 10]
    if len(setups) < 3:
        return {"value_pct": None, "pass": None,
                "note": "need >=3 setups with data for PBO; provisional."}
    df = df.sort_values("emit_date").reset_index(drop=True)
    blocks = np.array_split(df.index.values, n_blocks)
    # per-block, per-setup Sharpe matrix
    M = np.full((n_blocks, len(setups)), np.nan)
    for bi, idx in enumerate(blocks):
        sub = df.loc[idx]
        for si, s in enumerate(setups):
            r = sub.loc[sub["setup"] == s, "realized_R"].values
            M[bi, si] = _sharpe(r) if len(r) >= 3 else 0.0
    from itertools import combinations
    half = n_blocks // 2
    below = tot = 0
    for combo in combinations(range(n_blocks), half):
        is_rows = list(combo)
        oos_rows = [b for b in range(n_blocks) if b not in combo]
        is_sh = np.nanmean(M[is_rows, :], axis=0)
        oos_sh = np.nanmean(M[oos_rows, :], axis=0)
        best = int(np.nanargmax(is_sh))
        # rank of the IS-best setup in OOS (1=worst..N=best); below median?
        order = np.argsort(np.argsort(oos_sh))  # 0..N-1
        rel = (order[best] + 1) / (len(setups) + 1)
        below += int(rel <= 0.5)
        tot += 1
    pbo_pct = round(100.0 * below / tot, 1) if tot else None
    return {"value_pct": pbo_pct, "pass": (pbo_pct is not None and pbo_pct <= 20),
            "n_setups": len(setups), "combinations": tot,
            "note": "low PBO is good; <=20% passes. Short ledger => limited power."}


# ---------------------------------------------------------- Phase C: Deflated SR
def deflated_sharpe(df: pd.DataFrame) -> dict:
    R = df["realized_R"].values
    T = len(R)
    sr = _sharpe(R)
    sd = pd.Series(R)
    skew = float(sd.skew())
    kurt = float(sd.kurt()) + 3.0  # pandas kurt is excess; DSR wants non-excess
    # trials = setups tried (lower bound on the real search); their Sharpe spread
    setups = df["setup"].unique()
    trial_sr = [_sharpe(df.loc[df["setup"] == s, "realized_R"].values)
                for s in setups if (df["setup"] == s).sum() >= 3]
    N = max(len(trial_sr), 2)
    var_tr = float(np.var(trial_sr, ddof=1)) if len(trial_sr) > 1 else (sr * sr + 1e-6)
    sr0 = math.sqrt(var_tr) * ((1 - EULER) * Z(1 - 1.0 / N) + EULER * Z(1 - 1.0 / (N * math.e)))
    denom = math.sqrt(max(1e-9, 1 - skew * sr + ((kurt - 1) / 4.0) * sr * sr))
    dsr = PHI((sr - sr0) * math.sqrt(max(1, T - 1)) / denom)
    return {"per_trade_sharpe": round(sr, 3), "trials_N": N,
            "expected_max_sharpe_SR0": round(sr0, 3),
            "deflated_sharpe_prob": round(dsr, 3),
            "pass": dsr >= 0.95,
            "note": "P(true Sharpe>0 after correcting for N trials). >=0.95 passes."}


# ------------------------------------------------------- Phase C2: skill vs beta
def skill_vs_beta(df: pd.DataFrame, risk_pct: float) -> dict:
    spy = _spy_returns()
    # monthly strategy % return ≈ sum(R that month) × risk_pct/100
    g = df.set_index("emit_date").resample("ME")["realized_R"].sum() * (risk_pct / 100.0)
    spm = (1 + spy).resample("ME").prod() - 1
    j = pd.concat([g.rename("strat"), spm.rename("spy")], axis=1, sort=False).dropna()
    months = len(j)
    if months < 4:
        beta = alpha_ann = None
    else:
        cov = np.cov(j["strat"], j["spy"])
        beta = float(cov[0, 1] / cov[1, 1]) if cov[1, 1] > 0 else 0.0
        alpha_m = float(j["strat"].mean() - beta * j["spy"].mean())
        alpha_ann = round(alpha_m * 12 * 100, 2)
    alpha_reliable = months >= 12
    # matched-horizon random-long benchmark: P(SPY up over median hold)
    hold = int(df["hold_days"].median() or 8)
    fwd = _spy_returns().add(1).rolling(hold).apply(np.prod, raw=True) - 1
    rand_win = float((fwd.dropna() > 0).mean() * 100)
    strat_win = float((df["realized_R"] > 0).mean() * 100)
    beats_random = strat_win > rand_win + 3
    return {"beta_to_market": round(beta, 2) if beta is not None else None,
            "annualized_alpha_pct": alpha_ann, "months": months,
            "strategy_win_rate_pct": round(strat_win, 1),
            "random_long_win_rate_pct": round(rand_win, 1),
            "beats_random_entries": beats_random,
            "annualized_alpha_reliable": alpha_reliable,
            "pass": bool(beats_random and (alpha_ann is None or alpha_ann > 0)),
            "note": "skill must beat a matched-horizon random long; alpha should be "
                    ">0 net of market beta. ~8-month sample => alpha MAGNITUDE is an "
                    "unreliable artifact (ignore the headline %); the win-rate-vs-random "
                    "margin is the meaningful read."}


# --------------------------------------------------------- Phase E: cost & capacity
def break_even_cost() -> dict:
    sr = _report("scorecard-replay.json").get("overall", {})
    st = _report("stress-test.json")
    exp = sr.get("expectancy_R")
    cost = st.get("costs_R_per_trade", 0.03)
    if exp is None:
        return {"pass": None, "note": "no expectancy on file."}
    headroom = round(exp / cost, 1) if cost else None
    return {"net_expectancy_R": exp, "current_cost_R": cost,
            "break_even_extra_cost_R": round(exp, 3),
            "headroom_multiple": headroom,
            "pass": headroom is not None and headroom >= 2,
            "note": "edge dies when added cost ≈ net expectancy; >=2x headroom passes. "
                    "REPLAY/survivorship-inflated, so true headroom is lower."}


def capacity() -> dict:
    import duckdb
    c = duckdb.connect(str(PRICES), read_only=True)
    try:
        adv = c.execute(
            "SELECT MEDIAN(dv) FROM (SELECT ticker, MEDIAN(close*volume) dv FROM prices "
            "WHERE date > '2025-01-01' GROUP BY ticker)").fetchone()[0]
    finally:
        c.close()
    adv = float(adv or 0)
    # rough: position notional should stay under 1% of ADV; with ~0.5% risk and a
    # ~5% stop, notional ≈ 10× dollar_risk. cap where notional = 1% ADV.
    stop_frac, risk_pct = 0.05, 0.005
    notional_per_risk = 1.0 / stop_frac
    cap = (0.01 * adv) / (risk_pct * notional_per_risk) if adv else None
    return {"median_ADV_usd": round(adv), "capital_ceiling_usd_approx": round(cap) if cap else None,
            "pass": True, "note": "rough ADV-based ceiling (assumes ~5% stop, 1% ADV impact "
                                   "cap). For scaling guidance only, not a precise limit."}


# ------------------------------------------------------------ §4: fractional Kelly
def kelly(df: pd.DataFrame, risk_pct: float) -> dict:
    sr = _report("scorecard-replay.json").get("overall", {})
    p = (sr.get("win_rate", 0) or 0) / 100.0
    aw, al = sr.get("avg_win_R"), sr.get("avg_loss_R")
    if not (aw and al):
        return {"pass": None, "note": "no payoff data."}
    b = aw / abs(al)
    f_star = (p * b - (1 - p)) / b if b > 0 else 0.0
    used = risk_pct / 100.0
    half, quarter = f_star / 2, f_star / 4
    return {"kelly_fraction": round(f_star, 3), "half_kelly": round(half, 3),
            "quarter_kelly": round(quarter, 3), "risk_per_trade_used": used,
            "pass": used <= max(quarter, 0) if f_star > 0 else True,
            "note": "risk-per-trade should sit at/below ~quarter-Kelly. Note: if the "
                    "edge is inflated (it is — survivorship), Kelly is overstated, so "
                    "staying far below it is the correct, safe choice."}


# --------------------------------------------------------------- scorecard + verdict
def _clip(x):
    return max(0, min(100, int(round(x))))


def scorecard() -> dict:
    df = _ledger()
    risk_pct = 0.5
    try:
        import yaml
        rp = yaml.safe_load((ROOT / "config" / "risk_policy.yaml").read_text())
        def find(d, k):
            if isinstance(d, dict):
                for kk, v in d.items():
                    if kk == k:
                        return v
                    r = find(v, k)
                    if r is not None:
                        return r
            return None
        risk_pct = float(find(rp, "risk_per_trade_pct") or 0.5)
    except Exception:
        pass

    checks = {
        "pbo": pbo(df),
        "deflated_sharpe": deflated_sharpe(df),
        "skill_vs_beta": skill_vs_beta(df, risk_pct),
        "break_even_cost": break_even_cost(),
        "capacity": capacity(),
        "fractional_kelly": kelly(df, risk_pct),
    }
    wf = _report("walk-forward.json")
    mc = _report("monte-carlo.json")
    st = _report("stress-test.json")
    gl = _report("go-live.json")

    live_n = (_report("scorecard-replay.json").get("overall_live") or {}).get("n", 0) or 0
    ruin = (mc.get("risk_of_ruin") or {}).get("probability", 1.0)
    worst_regime = min((w.get("expectancy_R", 0) for w in (st.get("stress_windows") or {}).values()
                        if isinstance(w, dict)), default=-1)
    gap = wf.get("is_vs_oos_gap", 9)

    # dimension scores 0-100 (honest, evidence-based)
    dims = {
        "edge_persistence": _clip(60 - 20 * max(0, gap - 1.0)) if wf else 0,
        "overfitting_safety": _clip(100 - (checks["pbo"]["value_pct"] or 50)
                                    ) if checks["pbo"]["value_pct"] is not None else 30,
        "genuine_skill_vs_beta": 70 if checks["skill_vs_beta"]["pass"] else 25,
        "regime_robustness": _clip(50 + 40 * worst_regime),  # negative worst => low
        "cost_capacity_resilience": 80 if checks["break_even_cost"]["pass"] else 30,
        "tail_survival": _clip(100 - 5000 * ruin),
        "risk_of_ruin_safety": 100 if ruin < 0.01 else _clip(100 - 5000 * ruin),
        "param_noise_stability": 50,  # not yet measured here (walk-forward smoothness pending)
        "fail_safe_behavior": 90 if any(g.get("gate", "").startswith("6.") and g.get("status") == "PASS"
                                        for g in gl.get("gates", [])) else 40,
        "deflated_sharpe_significance": _clip(checks["deflated_sharpe"]["deflated_sharpe_prob"] * 100),
        "live_reconciliation": 0 if live_n == 0 else 50,
    }
    overall = round(sum(dims.values()) / len(dims), 1)

    # verdict (hard gates dominate; Phase K is required)
    hard_fail = []
    if live_n == 0:
        hard_fail.append("Phase K: no forward paper-trading record (required gate)")
    if checks["pbo"]["pass"] is False:
        hard_fail.append(f"Phase C: PBO {checks['pbo']['value_pct']}% too high")
    if checks["deflated_sharpe"]["pass"] is False:
        hard_fail.append("Phase C: Deflated Sharpe not significant for the track length")
    if checks["skill_vs_beta"]["pass"] is False:
        hard_fail.append("Phase C2: does not clearly beat market beta / random entries")
    if worst_regime < -0.4:
        hard_fail.append(f"Phase D: severe loss in worst regime ({worst_regime:+.2f}R/trade)")
    if gap > 1.5:
        hard_fail.append(f"Phase B/C: in-sample/out-of-sample Sharpe gap {gap} too large")

    verdict = "APPROVED" if (not hard_fail and overall >= 70) else (
        "CONDITIONAL" if (overall >= 45 and len(hard_fail) <= 1) else "REJECTED")
    # survivorship + short track are standing constraints; never APPROVED on replay
    if live_n == 0:
        verdict = "REJECTED"

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "evidence": "REPLAY ledger (~8 months, survivorship-biased) — indicative only.",
        "checks": checks,
        "scorecard_0_100": dims,
        "overall_score": overall,
        "verdict": verdict,
        "hard_gate_failures": hard_fail,
        "disclaimer": ("Surviving this gauntlet would lower the chance of catastrophic "
                       "failure; it never promises profit. Outputs are informational, not "
                       "financial advice. Markets risk total loss of capital."),
    }


def render(r: dict) -> str:
    L = [f"# Validation Gauntlet — verdict: {r['verdict']}",
         f"_{r['asof']} · evidence: {r['evidence']}_",
         f"\n**Overall robustness score: {r['overall_score']}/100**\n",
         "## Scorecard (0-100)"]
    for k, v in r["scorecard_0_100"].items():
        L.append(f"- {k.replace('_',' ')}: {v}")
    L.append("\n## Institutional checks")
    c = r["checks"]
    L.append(f"- PBO (overfitting prob): {c['pbo']['value_pct']}% "
             f"({'pass' if c['pbo']['pass'] else 'FAIL/provisional'})")
    L.append(f"- Deflated Sharpe: {c['deflated_sharpe']['deflated_sharpe_prob']} "
             f"({'pass' if c['deflated_sharpe']['pass'] else 'FAIL'})")
    L.append(f"- Skill vs beta: win {c['skill_vs_beta']['strategy_win_rate_pct']}% vs random "
             f"{c['skill_vs_beta']['random_long_win_rate_pct']}%, alpha "
             f"{c['skill_vs_beta']['annualized_alpha_pct']}%/yr "
             f"({'pass' if c['skill_vs_beta']['pass'] else 'FAIL'})")
    L.append(f"- Break-even cost headroom: {c['break_even_cost']['headroom_multiple']}x "
             f"({'pass' if c['break_even_cost']['pass'] else 'FAIL'})")
    L.append(f"- Capacity ceiling (approx): ${c['capacity']['capital_ceiling_usd_approx']:,}"
             if c['capacity']['capital_ceiling_usd_approx'] else "- Capacity: n/a")
    L.append(f"- Fractional Kelly: f*={c['fractional_kelly']['kelly_fraction']}, using "
             f"{c['fractional_kelly']['risk_per_trade_used']} "
             f"({'pass' if c['fractional_kelly']['pass'] else 'FAIL'})")
    if r["hard_gate_failures"]:
        L += ["\n## Hard gate failures", *[f"- {h}" for h in r["hard_gate_failures"]]]
    L.append(f"\n_{r['disclaimer']}_")
    return "\n".join(L)


def main():
    r = scorecard()
    (REPORTS / "gauntlet.json").write_text(json.dumps(r, indent=2, default=str))
    print(json.dumps(r, indent=2, default=str) if "--json" in sys.argv else render(r))


if __name__ == "__main__":
    main()
