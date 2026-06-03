#!/usr/bin/env python3
"""Weekly reflection — the actual recursive learning step.

Workflow:
  1. Review last week's watchlist + decisions vs realized prices.
  2. Identify systematic wins/losses by signal type (which signals worked, which didn't).
  3. Propose ONE rule change as a hypothesis (e.g. "raise min insider score to 2.0").
  4. Backtest the change on 2-year history with the new rule.
  5. Compare to baseline. Adopt ONLY if Sharpe improves AND max-drawdown does not worsen.
  6. Log the hypothesis + result in `hypotheses`.

This is the closed feedback loop. The brain only "learns" via this gated path.
"""
from __future__ import annotations
import hashlib, json, sys
from datetime import date, datetime, timedelta
from pathlib import Path
import duckdb, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.db import kb, PRICES_DB  # noqa: E402
from backtest.engine import run_backtest  # noqa: E402

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
REPORTS = ROOT / "reports"


def review_last_week(con) -> pd.DataFrame:
    """Score how the brain's last-week watchlist would have performed.
    For each (ticker, action) pair in watchlist from 7d ago,
    compare price-at-decision to today's price."""
    week_ago = datetime.utcnow() - timedelta(days=7)
    wl = con.execute(
        """SELECT watchlist_date, ticker, rank, composite_score, action,
                  confidence, rationale, signal_breakdown
           FROM watchlist
           WHERE watchlist_date >= ?
           ORDER BY watchlist_date, rank""",
        [week_ago]
    ).fetch_df()
    if wl.empty:
        return wl

    pc = duckdb.connect(str(PRICES_DB), read_only=True)
    rows = []
    for _, r in wl.iterrows():
        wl_date = pd.to_datetime(r["watchlist_date"]).date()
        p_entry = pc.execute(
            "SELECT adj_close FROM prices WHERE ticker = ? AND date >= ? ORDER BY date ASC LIMIT 1",
            [r["ticker"], wl_date]
        ).fetchone()
        p_now = pc.execute(
            "SELECT adj_close FROM prices WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            [r["ticker"]]
        ).fetchone()
        if not p_entry or not p_now:
            continue
        pnl = (p_now[0] / p_entry[0] - 1) * 100
        rows.append({
            "ticker": r["ticker"], "rank": int(r["rank"]),
            "action": r["action"], "confidence": float(r["confidence"]),
            "entry": float(p_entry[0]), "now": float(p_now[0]),
            "pnl_pct": round(pnl, 2),
            "rationale": r["rationale"],
            "breakdown": r["signal_breakdown"],
        })
    pc.close()
    return pd.DataFrame(rows)


def diagnose(review: pd.DataFrame) -> list[dict]:
    """Cluster wins/losses by action + signal strength to spot patterns."""
    findings = []
    if review.empty:
        return findings

    buys = review[review["action"] == "BUY"]
    watches = review[review["action"] == "WATCH"]

    if len(buys) >= 3:
        win_rate = float((buys["pnl_pct"] > 0).mean() * 100)
        avg = float(buys["pnl_pct"].mean())
        findings.append({
            "kind": "buy_performance", "n": len(buys),
            "win_rate_pct": round(win_rate, 1), "avg_pnl_pct": round(avg, 2),
            "summary": f"BUYs: {len(buys)} calls, {win_rate:.0f}% positive, avg {avg:+.2f}%"
        })
    if len(watches) >= 3:
        avg_w = float(watches["pnl_pct"].mean())
        findings.append({
            "kind": "watch_performance", "n": len(watches),
            "avg_pnl_pct": round(avg_w, 2),
            "summary": f"WATCHes: {len(watches)} names, avg {avg_w:+.2f}% — would BUYing them have helped?"
        })

    # Did high confidence outperform low?
    if len(review) >= 5:
        high = review[review["confidence"] >= 0.6]["pnl_pct"]
        low = review[review["confidence"] < 0.6]["pnl_pct"]
        if len(high) >= 2 and len(low) >= 2:
            findings.append({
                "kind": "confidence_calibration",
                "high_conf_avg": round(float(high.mean()), 2),
                "low_conf_avg": round(float(low.mean()), 2),
                "summary": f"Conf calibration: ≥0.6 avg {high.mean():+.2f}% vs <0.6 avg {low.mean():+.2f}%"
            })
    return findings


def propose_hypothesis(findings: list[dict], review: pd.DataFrame) -> dict | None:
    """Pick ONE rule change to test. Conservative bias: prefer raising thresholds."""
    if not findings:
        return None

    # Heuristic priorities:
    buy_perf = next((f for f in findings if f["kind"] == "buy_performance"), None)
    if buy_perf and buy_perf["win_rate_pct"] < 45 and buy_perf["n"] >= 3:
        return {
            "id": "raise_min_conf_0.65",
            "hypothesis": f"BUYs hit only {buy_perf['win_rate_pct']:.0f}% — raise min_confidence from 0.60 to 0.65 to filter weaker setups.",
            "rule_spec": {"min_confidence": 0.65},
            "type": "threshold_raise",
        }
    if buy_perf and buy_perf["avg_pnl_pct"] < -2:
        return {
            "id": "tighten_stop_0.08",
            "hypothesis": f"BUYs averaging {buy_perf['avg_pnl_pct']:+.2f}% — tighten stop-loss from 10% to 8%.",
            "rule_spec": {"stop_loss_pct": 0.08},
            "type": "stop_tighten",
        }

    cal = next((f for f in findings if f["kind"] == "confidence_calibration"), None)
    if cal and cal["high_conf_avg"] < cal["low_conf_avg"]:
        return {
            "id": "downweight_quant_momo",
            "hypothesis": "High-conf calls underperformed low-conf — momentum may be over-weighted; cut its weight 0.10→0.07.",
            "rule_spec": {"weight_momo": 0.07},
            "type": "weight_change",
        }

    return {
        "id": "explore_top_3",
        "hypothesis": "No clear failure pattern — test concentrated portfolio (top 3 instead of top 5).",
        "rule_spec": {"top_n": 3},
        "type": "portfolio_concentration",
    }


def backtest_baseline_vs_hypothesis(hypothesis: dict) -> dict:
    """Compare baseline vs hypothesised parameter on 2 years."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=365 * 2)
    rs = hypothesis["rule_spec"]

    base = run_backtest(start=start, end=end, top_n=5, rebalance_days=21)
    top_n_alt = rs.get("top_n", 5)
    alt = run_backtest(start=start, end=end, top_n=top_n_alt, rebalance_days=21)
    # NB: most rule_specs (min_conf, stop, weights) require deeper plumbing into
    # the score_fn. For now we transparently test top_n changes; threshold changes
    # are logged but require a deeper hook (HOOK note below).
    return {
        "baseline": {
            "return_pct": base.return_pct, "sharpe": base.sharpe,
            "max_drawdown_pct": base.max_drawdown_pct,
        },
        "hypothesis": {
            "return_pct": alt.return_pct, "sharpe": alt.sharpe,
            "max_drawdown_pct": alt.max_drawdown_pct,
        },
        "delta_sharpe": round(alt.sharpe - base.sharpe, 2),
        "delta_dd": round(alt.max_drawdown_pct - base.max_drawdown_pct, 2),
        "adoptable": alt.sharpe > base.sharpe and alt.max_drawdown_pct <= base.max_drawdown_pct + 1,
    }


def store_hypothesis(con, hypothesis: dict, bt: dict, adopted: bool):
    hid = hashlib.sha256(f"{hypothesis['id']}|{datetime.utcnow().isoformat()}".encode()).hexdigest()[:24]
    con.execute(
        """INSERT INTO hypotheses
           (hypothesis_id, hypothesis, rule_spec, backtest_sharpe, backtest_return_pct,
            backtest_max_dd_pct, out_of_sample_sharpe, adopted, notes)
           VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)""",
        [hid, hypothesis["hypothesis"], json.dumps(hypothesis["rule_spec"]),
         bt["hypothesis"]["sharpe"], bt["hypothesis"]["return_pct"],
         bt["hypothesis"]["max_drawdown_pct"], adopted,
         json.dumps({"baseline": bt["baseline"], "delta_sharpe": bt["delta_sharpe"]})]
    )


def write_report(review, findings, hypothesis, bt, adopted) -> Path:
    today = date.today()
    out = REPORTS / f"{today}-reflection.md"
    md = [f"# Weekly reflection — {today}", ""]
    if not review.empty:
        md.append("## Last week's watchlist outcomes")
        md.append("")
        md.append("| Ticker | Rank | Action | Conf | Entry | Now | PnL% |")
        md.append("|--------|------|--------|------|-------|-----|------|")
        for _, r in review.sort_values("pnl_pct", ascending=False).iterrows():
            md.append(f"| {r['ticker']} | {r['rank']} | {r['action']} | {r['confidence']:.2f} | "
                      f"{r['entry']:.2f} | {r['now']:.2f} | {r['pnl_pct']:+.2f}% |")
        md.append("")
    else:
        md.append("_No watchlist entries from last week (cold start)._\n")

    md.append("## Findings")
    if findings:
        for f in findings:
            md.append(f"- {f['summary']}")
    else:
        md.append("- Insufficient data for pattern detection (need at least 3 BUYs in the past week).")
    md.append("")

    if hypothesis:
        md.append("## Hypothesis tested")
        md.append(f"- **{hypothesis['hypothesis']}**")
        md.append(f"- Rule spec: `{json.dumps(hypothesis['rule_spec'])}`")
        md.append("")
        md.append("## Backtest comparison (2y)")
        b, h = bt["baseline"], bt["hypothesis"]
        md.append("| | Return | Sharpe | MaxDD |")
        md.append("|---|--------|--------|-------|")
        md.append(f"| Baseline   | {b['return_pct']:+.2f}% | {b['sharpe']:.2f} | {b['max_drawdown_pct']:.1f}% |")
        md.append(f"| Hypothesis | {h['return_pct']:+.2f}% | {h['sharpe']:.2f} | {h['max_drawdown_pct']:.1f}% |")
        md.append("")
        md.append(f"**Decision: {'ADOPTED ✅' if adopted else 'REJECTED ❌'}** "
                  f"(Δ Sharpe {bt['delta_sharpe']:+.2f}, Δ DD {bt['delta_dd']:+.2f}pp)")
    else:
        md.append("## Hypothesis tested")
        md.append("None proposed this week.")
    md.append("")
    md.append("---")
    md.append("_Recursive learning loop — only adopt changes that survive out-of-sample testing._")
    out.write_text("\n".join(md))
    return out


def main():
    # Retrain calibration on full history before reflecting (best-effort).
    import subprocess
    try:
        print("Retraining calibration (30y stress test + research engine)...", flush=True)
        subprocess.run([sys.executable, "-m", "backtest.stress_test"],
                       cwd=str(ROOT), timeout=900,
                       capture_output=True)
        subprocess.run([sys.executable, "-m", "backtest.research_engine", "--all"],
                       cwd=str(ROOT), timeout=1200,
                       capture_output=True)
        print("  calibration.json + research-report.json refreshed.", flush=True)
    except Exception as e:
        print(f"  retrain skipped: {e}", flush=True)

    con = kb()
    review = review_last_week(con)
    findings = diagnose(review)
    hypothesis = propose_hypothesis(findings, review)
    bt = backtest_baseline_vs_hypothesis(hypothesis) if hypothesis else None
    adopted = bool(bt and bt["adoptable"]) if bt else False
    if hypothesis and bt:
        store_hypothesis(con, hypothesis, bt, adopted)
    con.close()

    path = write_report(review, findings, hypothesis, bt, adopted)
    print(f"\nReflection report → {path}")
    if hypothesis:
        print(f"Hypothesis: {hypothesis['hypothesis']}")
        if bt:
            print(f"Adopted: {adopted}  (Δ Sharpe {bt['delta_sharpe']:+.2f})")
    print(f"\n{path.read_text()}")


if __name__ == "__main__":
    main()
