#!/usr/bin/env python3
"""Monte Carlo trade-resampling — spec Phase 5.2 & 6.2 ("the right way").

The mandate (master prompt §1.6): do NOT run a million parameter sets and keep
the luckiest. Hold the logic fixed and resample the *trade sequence* thousands of
times, to learn the DISTRIBUTION of outcomes — especially how ugly the bad tail
of drawdown gets — rather than a single flattering number.

Input: the resolved trade ledger (realized R-multiples) in signal_ledger.
Output: distributions for total return (R) and max drawdown (R + approx %equity),
with confidence bands and explicit worst-case, written to reports/monte-carlo.json.

Honesty: defaults to REPLAY trades only and labels them survivorship-biased /
indicative. It never invents trades — it only reshuffles ones that were recorded.

CLI:
  python3 -m backtest.monte_carlo                 # 10k paths on replay ledger
  python3 -m backtest.monte_carlo --paths 50000   # more paths
  python3 -m backtest.monte_carlo --source live   # only true live fills (may be ~0)
"""
from __future__ import annotations
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT

KB = ROOT / "data" / "knowledge.duckdb"
OUT = ROOT / "reports" / "monte-carlo.json"


def _load_R(source: str | None) -> tuple[np.ndarray, int, int]:
    import duckdb
    con = duckdb.connect(str(KB), read_only=True)
    q = "SELECT realized_R, source FROM signal_ledger WHERE realized_R IS NOT NULL"
    try:
        rows = con.execute(q).fetchall()
    finally:
        con.close()
    n_live = sum(1 for _, s in rows if s == "live")
    n_replay = sum(1 for _, s in rows if s == "replay")
    if source in ("live", "replay"):
        rows = [r for r in rows if r[1] == source]
    return np.array([float(r[0]) for r in rows], dtype=float), n_live, n_replay


def _max_drawdown_R(equity: np.ndarray) -> float:
    """Peak-to-trough drawdown of a cumulative-R equity curve, in R."""
    peak = np.maximum.accumulate(equity)
    return float(np.max(peak - equity)) if equity.size else 0.0


def _risk_per_trade_pct() -> float:
    try:
        import yaml
        rp = yaml.safe_load((ROOT / "config" / "risk_policy.yaml").read_text())
        # nested or flat — find the first matching key
        def find(d):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k == "risk_per_trade_pct":
                        return float(v)
                    r = find(v)
                    if r is not None:
                        return r
            return None
        return find(rp) or 0.5
    except Exception:
        return 0.5


def _resample_iid(R: np.ndarray, rng) -> np.ndarray:
    """IID bootstrap: independent draws with replacement. Breaks up losing
    streaks, so it UNDERSTATES drawdown for any system with serial dependence."""
    n = R.size
    return R[rng.integers(0, n, size=n)]


def _resample_block(R: np.ndarray, rng, mean_block: int = 10) -> np.ndarray:
    """Stationary block bootstrap: draw contiguous blocks of trades so that
    real-world clustering of losses (the thing that actually causes deep
    drawdowns) is preserved. This is the honest drawdown estimate."""
    n = R.size
    out, p = [], 1.0 / mean_block
    while len(out) < n:
        start = rng.integers(0, n)
        length = rng.geometric(p)
        for j in range(length):
            out.append(R[(start + j) % n])
            if len(out) >= n:
                break
    return np.array(out[:n])


def run(paths: int = 10000, source: str | None = "replay", seed: int = 7,
        method: str = "block", mean_block: int = 10) -> dict:
    R, n_live, n_replay = _load_R(source)
    n = R.size
    if n < 20:
        return {"error": f"only {n} resolved trades for source={source} — "
                         "not enough to resample into a distribution."}

    rng = np.random.default_rng(seed)
    resample = _resample_block if method == "block" else _resample_iid

    finals = np.empty(paths)
    max_dds = np.empty(paths)
    longest_streaks = np.empty(paths)
    recovered = 0
    recov_times = []
    for i in range(paths):
        seq = resample(R, rng, mean_block) if method == "block" else resample(R, rng)
        equity = np.cumsum(seq)
        finals[i] = equity[-1]
        peak = np.maximum.accumulate(equity)
        dd_series = peak - equity
        max_dds[i] = float(np.max(dd_series)) if dd_series.size else 0.0
        # longest losing streak (consecutive negative trades)
        neg = seq < 0
        streak = mx = 0
        for v in neg:
            streak = streak + 1 if v else 0
            mx = max(mx, streak)
        longest_streaks[i] = mx
        # time-to-recovery: bars from the max-drawdown trough back to its prior peak
        if dd_series.size:
            trough = int(np.argmax(dd_series))
            peak_val = peak[trough]
            after = equity[trough:]
            rec = np.where(after >= peak_val)[0]
            if rec.size:
                recovered += 1
                recov_times.append(int(rec[0]))

    rpt = _risk_per_trade_pct()
    max_concurrent = 6
    try:
        import yaml
        rp = yaml.safe_load((ROOT / "config" / "risk_policy.yaml").read_text())
        def find(d, key):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k == key:
                        return v
                    r = find(v, key)
                    if r is not None:
                        return r
            return None
        max_concurrent = int(find(rp, "max_concurrent_positions") or 6)
    except Exception:
        pass

    def pct(a, p):
        return round(float(np.percentile(a, p)), 2)

    def dd_pct(p):
        return round(float(np.percentile(max_dds, p)) * rpt, 1)

    dd_ceiling_pct = 20.0
    try:
        import yaml
        g = yaml.safe_load((ROOT / "config" / "goal.yaml").read_text())
        dd_ceiling_pct = float(g.get("success", {}).get("max_drawdown_pct", 20))
    except Exception:
        pass
    breach = float(np.mean((max_dds * rpt) > dd_ceiling_pct))
    # Risk of ruin (Phase G): fraction of paths whose drawdown breaches a ruin
    # level in %equity terms. Default ruin = 50% of capital; tolerance < 1%.
    ruin_pct = 50.0
    risk_of_ruin = float(np.mean((max_dds * rpt) >= ruin_pct))
    import numpy as _np
    recov_med = int(_np.median(recov_times)) if recov_times else None
    recov_p95 = int(_np.percentile(recov_times, 95)) if recov_times else None

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "paths": paths, "trades_per_path": int(n), "seed": seed,
        "source": source, "method": method,
        "method_note": ("block bootstrap (streak-preserving) — the honest drawdown "
                        "estimate" if method == "block" else
                        "IID bootstrap — UNDERSTATES drawdown (breaks losing streaks)"),
        "ledger_counts": {"live": n_live, "replay": n_replay},
        "honesty_note": ("Resampled from REPLAY trades (survivorship-biased, "
                         "INDICATIVE only) unless source=live. No trades are "
                         "invented; only recorded R-multiples are reshuffled."),
        "risk_per_trade_pct_assumed": rpt,
        "concurrency_caveat": (f"%-drawdown assumes NON-overlapping positions, but "
                               f"policy allows {max_concurrent} concurrent — real "
                               f"%-equity drawdown can be up to ~{max_concurrent}x "
                               "worse if positions are correlated and lose together."),
        "total_return_R": {
            "p5": pct(finals, 5), "p50": pct(finals, 50), "p95": pct(finals, 95),
            "worst_p1": pct(finals, 1), "min": round(float(finals.min()), 2)},
        "max_drawdown_R": {
            "p50": pct(max_dds, 50), "p95": pct(max_dds, 95),
            "p99": pct(max_dds, 99), "worst_max": round(float(max_dds.max()), 2)},
        "max_drawdown_pct_approx": {
            "p50": dd_pct(50), "p95": dd_pct(95), "p99": dd_pct(99),
            "note": f"≈ R-drawdown × {rpt}%/trade, single-position approximation "
                    "(see concurrency_caveat)."},
        "drawdown_ceiling_pct": dd_ceiling_pct,
        "prob_breach_ceiling": round(breach, 4),
        "risk_of_ruin": {
            "ruin_level_pct_equity": ruin_pct, "probability": round(risk_of_ruin, 5),
            "tolerance": 0.01, "pass": risk_of_ruin < 0.01,
            "note": "P(equity drawdown >= ruin level) across resampled orderings; "
                    "tests sequence-of-returns risk. REPLAY-based unless source=live."},
        "longest_losing_streak": {
            "p50": int(np.percentile(longest_streaks, 50)),
            "p95": int(np.percentile(longest_streaks, 95)),
            "worst": int(longest_streaks.max())},
        "time_to_recovery_trades": {
            "recovered_fraction": round(recovered / paths, 3),
            "median": recov_med, "p95": recov_p95},
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paths", type=int, default=10000)
    ap.add_argument("--source", default="replay", choices=["replay", "live", "all"])
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--method", default="block", choices=["block", "iid"])
    a = ap.parse_args()
    src = None if a.source == "all" else a.source
    rep = run(paths=a.paths, source=src, seed=a.seed, method=a.method)
    OUT.write_text(json.dumps(rep, indent=2, default=str))
    if "error" in rep:
        print("Monte Carlo:", rep["error"])
        return
    tr, dd, ddp = rep["total_return_R"], rep["max_drawdown_R"], rep["max_drawdown_pct_approx"]
    print(f"Monte Carlo — {rep['paths']:,} resampled histories of {rep['trades_per_path']} trades "
          f"(source={rep['source']}, method={rep['method']})")
    print(f"  {rep['method_note']}")
    print(f"  total return (R):  p5 {tr['p5']}  median {tr['p50']}  p95 {tr['p95']}  worst {tr['min']}")
    print(f"  max drawdown (R):  median {dd['p50']}  p95 {dd['p95']}  p99 {dd['p99']}  worst {dd['worst_max']}")
    print(f"  max drawdown (~%): median {ddp['p50']}%  p95 {ddp['p95']}%  p99 {ddp['p99']}%  "
          f"(ceiling {rep['drawdown_ceiling_pct']}%)")
    print(f"  P(drawdown breaches {rep['drawdown_ceiling_pct']}% ceiling): {rep['prob_breach_ceiling']*100:.1f}%")
    print(f"  caveat: {rep['concurrency_caveat']}")
    print(f"  {rep['honesty_note']}")


if __name__ == "__main__":
    main()
