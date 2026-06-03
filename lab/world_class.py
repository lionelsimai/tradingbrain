#!/usr/bin/env python3
"""TradingBrain world-class readiness scorecard.

This module is deliberately *not* a trading signal. It is an institutional
readiness audit that measures the concrete evidence needed for TradingBrain to
become a top-tier quant stock recommender: clean point-in-time data, real
forward paper records, benchmark-adjusted edge, risk controls, auditability,
automation, and live-safety discipline.

It stays honest: missing survivorship-free data or a forward paper record is a
hard blocker no matter how good replay/backtest artifacts look.

Run:
  python3 -m lab.world_class          # writes reports + markdown
  python3 -m lab.world_class --json   # machine-readable
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT  # noqa: E402

REPORTS = ROOT / "reports"
DATA = ROOT / "data"
OUT_JSON = REPORTS / "world-class-readiness.json"
OUT_MD = ROOT / "WORLD-CLASS-READINESS.md"


WEIGHTS = {
    "Survivorship-free data": 18,
    "Forward paper record": 22,
    "Benchmark-adjusted edge": 16,
    "Risk controls": 14,
    "Explainability and audit trail": 10,
    "Automation reliability": 8,
    "Validation rigor": 8,
    "Live safety governance": 4,
}


def _clip_score(score: float | int | None) -> int:
    try:
        if score is None or math.isnan(float(score)):
            return 0
        return max(0, min(100, int(round(float(score)))))
    except Exception:
        return 0


def score_dimension(name: str, score: float | int | None, status: str, evidence: str, action: str) -> dict:
    """Build a normalized dimension row with clamped 0-100 score."""
    return {
        "name": name,
        "weight_pct": WEIGHTS.get(name, 0),
        "score": _clip_score(score),
        "status": status,
        "evidence": evidence,
        "action": action,
    }


def _load_report(name: str, default: Any = None) -> Any:
    try:
        return json.loads((REPORTS / name).read_text())
    except Exception:
        return {} if default is None else default


def _table_counts() -> dict:
    out = {"prices_rows": 0, "universe_rows": 0, "delisted_rows": 0,
           "polygon_inactive_rows": 0, "polygon_corporate_action_rows": 0,
           "paper_fills": 0,
           "paper_orders": 0, "paper_positions": 0, "signal_ledger_resolved": 0,
           "signal_ledger_replay": 0, "signal_ledger_live_or_paper": 0,
           "forward_paper_observations": 0, "forward_paper_resolved": 0,
           "forward_paper_horizon_outcomes": 0,
           "analyst_target_records": 0}
    try:
        import duckdb
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    prices = DATA / "prices.duckdb"
    if prices.exists():
        con = None
        try:
            con = duckdb.connect(str(prices), read_only=True)
            tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "prices" in tables:
                out["prices_rows"] = int(con.execute("SELECT COUNT(*) FROM prices").fetchone()[0] or 0)
            if "universe" in tables:
                out["universe_rows"] = int(con.execute("SELECT COUNT(*) FROM universe").fetchone()[0] or 0)
                # DuckDB DESCRIBE rows are (column_name, column_type, ...). Use r[0], not r[1].
                cols = {str(r[0]) for r in con.execute("DESCRIBE universe").fetchall()}
                if "active" in cols and "delisted_at" in cols:
                    out["delisted_rows"] = int(con.execute(
                        "SELECT COUNT(*) FROM universe WHERE active = false OR delisted_at IS NOT NULL"
                    ).fetchone()[0] or 0)
                elif "active" in cols:
                    out["delisted_rows"] = int(con.execute(
                        "SELECT COUNT(*) FROM universe WHERE active = false"
                    ).fetchone()[0] or 0)
                elif "delisted_at" in cols:
                    out["delisted_rows"] = int(con.execute(
                        "SELECT COUNT(*) FROM universe WHERE delisted_at IS NOT NULL"
                    ).fetchone()[0] or 0)
        except Exception as e:
            out["prices_error"] = f"{type(e).__name__}: {e}"
        finally:
            if con is not None:
                con.close()

    kb = DATA / "knowledge.duckdb"
    if kb.exists():
        con = None
        try:
            con = duckdb.connect(str(kb), read_only=True)
            tables = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
            if "paper_fills" in tables:
                out["paper_fills"] = int(con.execute("SELECT COUNT(*) FROM paper_fills").fetchone()[0] or 0)
            if "paper_orders" in tables:
                out["paper_orders"] = int(con.execute("SELECT COUNT(*) FROM paper_orders").fetchone()[0] or 0)
            if "paper_positions" in tables:
                out["paper_positions"] = int(con.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0] or 0)
            if "signal_ledger" in tables:
                out["signal_ledger_resolved"] = int(con.execute(
                    "SELECT COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL"
                ).fetchone()[0] or 0)
                out["signal_ledger_replay"] = int(con.execute(
                    "SELECT COUNT(*) FROM signal_ledger WHERE COALESCE(source, '') = 'replay'"
                ).fetchone()[0] or 0)
                out["signal_ledger_live_or_paper"] = int(con.execute(
                    "SELECT COUNT(*) FROM signal_ledger WHERE COALESCE(source, '') IN ('live','paper')"
                ).fetchone()[0] or 0)
            if "polygon_tickers" in tables:
                out["polygon_inactive_rows"] = int(con.execute(
                    "SELECT COUNT(*) FROM polygon_tickers WHERE active = false"
                ).fetchone()[0] or 0)
            if "forward_paper_observations" in tables:
                out["forward_paper_observations"] = int(con.execute(
                    "SELECT COUNT(*) FROM forward_paper_observations"
                ).fetchone()[0] or 0)
                out["forward_paper_resolved"] = int(con.execute(
                    "SELECT COUNT(*) FROM forward_paper_observations WHERE realized_R IS NOT NULL OR status='resolved'"
                ).fetchone()[0] or 0)
            if "forward_paper_horizon_outcomes" in tables:
                out["forward_paper_horizon_outcomes"] = int(con.execute(
                    "SELECT COUNT(*) FROM forward_paper_horizon_outcomes"
                ).fetchone()[0] or 0)
            if "analyst_targets" in tables:
                out["analyst_target_records"] = int(con.execute(
                    "SELECT COUNT(*) FROM analyst_targets"
                ).fetchone()[0] or 0)
            corp_total = 0
            if "polygon_splits" in tables:
                corp_total += int(con.execute("SELECT COUNT(*) FROM polygon_splits").fetchone()[0] or 0)
            if "polygon_dividends" in tables:
                corp_total += int(con.execute("SELECT COUNT(*) FROM polygon_dividends").fetchone()[0] or 0)
            out["polygon_corporate_action_rows"] = corp_total
        except Exception as e:
            out["knowledge_error"] = f"{type(e).__name__}: {e}"
        finally:
            if con is not None:
                con.close()
    return out


def _data_dimension(counts: dict) -> tuple[dict, bool]:
    has_prices = counts.get("prices_rows", 0) > 0
    has_universe = counts.get("universe_rows", 0) > 0
    has_delisted = counts.get("delisted_rows", 0) > 0
    has_polygon_inactive = counts.get("polygon_inactive_rows", 0) > 0
    has_polygon_corporate_actions = counts.get("polygon_corporate_action_rows", 0) > 0
    score = 25 * has_prices + 25 * has_universe + 30 * has_delisted + 10 * has_polygon_inactive + 10 * has_polygon_corporate_actions
    if not has_delisted:
        # Polygon reference/corporate-action evidence is useful, but it is not
        # equivalent to a delisted-inclusive point-in-time price/universe table.
        score = min(score, 75)
    status = "pass" if has_delisted and has_polygon_corporate_actions else ("partial" if has_prices and has_universe else "fail")
    evidence = (
        f"prices_rows={counts.get('prices_rows', 0)}, universe_rows={counts.get('universe_rows', 0)}, "
        f"delisted_rows={counts.get('delisted_rows', 0)}, polygon_inactive_rows={counts.get('polygon_inactive_rows', 0)}, "
        f"polygon_corporate_action_rows={counts.get('polygon_corporate_action_rows', 0)}"
    )
    if not has_delisted:
        action = ("Polygon inactive/corporate-action reference is now being collected; next promote it into a delisted-inclusive, "
                  "point-in-time universe/price store, or import a vendor PIT export (Sharadar/Norgate/Intrinio).")
    else:
        action = "Keep auditing point-in-time timestamps, symbol changes, splits, dividends, and data revisions."
    return score_dimension("Survivorship-free data", score, status, evidence, action), not has_delisted


def _paper_dimension(counts: dict) -> tuple[dict, bool]:
    live_or_paper = counts.get("signal_ledger_live_or_paper", 0)
    fills = counts.get("paper_fills", 0)
    resolved_forward = counts.get("forward_paper_resolved", 0)
    horizon_outcomes = counts.get("forward_paper_horizon_outcomes", 0)
    pending_observations = counts.get("forward_paper_observations", 0)
    n = max(live_or_paper, fills, resolved_forward, horizon_outcomes)
    # Pending observations prove the logging spine exists, but world-class evidence still requires resolved outcomes.
    pending_credit = min(15, pending_observations / 200 * 15) if n < 50 else 0
    score = min(100, (n / 200) * 100 + pending_credit)
    status = "pass" if n >= 200 else ("partial" if n >= 50 or pending_observations > 0 else "fail")
    evidence = (f"forward_live_or_paper_signals={live_or_paper}, paper_fills={fills}, "
                f"forward_observations={pending_observations}, resolved_forward={resolved_forward}, "
                f"horizon_outcomes={horizon_outcomes}, required_for_world_class=200+ resolved")
    action = ("Run the paper engine every market day and log accepted/rejected signals, fills, exits, slippage, and thesis reviews "
              "until there are at least 200 resolved forward paper observations across regimes."
              if n < 200 else
              "Continue collecting forward paper records and compare actual fills against backtest assumptions monthly.")
    return score_dimension("Forward paper record", score, status, evidence, action), n < 50


def _benchmark_dimension() -> dict:
    wf = _load_report("walk-forward.json")
    gauntlet = _load_report("gauntlet.json")
    skill = ((gauntlet.get("checks") or {}).get("skill_vs_beta") or {})
    windows = int(wf.get("windows", 0) or 0)
    beat = int(wf.get("windows_beating_spy", 0) or 0)
    oos = wf.get("median_oos_sharpe")
    gap = wf.get("is_vs_oos_gap")
    skill_pass = bool(skill.get("pass"))
    score = 0
    if windows:
        score += 35 * (beat / max(windows, 1))
    if oos is not None:
        score += 30 if oos >= 0.5 else max(0, 30 * (float(oos) / 0.5))
    if gap is not None:
        score += 20 if gap <= 1.0 else max(0, 20 - 10 * (float(gap) - 1.0))
    score += 15 if skill_pass else 0
    status = "pass" if score >= 80 else ("partial" if score >= 45 else "fail")
    return score_dimension(
        "Benchmark-adjusted edge", score, status,
        f"walk_forward_windows={windows}, beats_SPY={beat}/{windows}, median_oos_sharpe={oos}, IS_OOS_gap={gap}, skill_vs_beta_pass={skill_pass}",
        "Require durable OOS edge versus SPY/QQQ/SMH/XLK and simple momentum baselines after costs; reduce or reject setups with unstable OOS gaps.",
    )


def _risk_dimension() -> dict:
    rp = _load_report("risk-policy-report.json")
    cb = _load_report("circuit-breakers.json")
    dq = _load_report("data-quality.json")
    safety = _load_report("safety_state.json")
    pieces = [bool(rp.get("valid")), cb != {}, bool(dq.get("pass")), safety != {}]
    score = sum(pieces) / len(pieces) * 100
    return score_dimension(
        "Risk controls", score, "pass" if score >= 90 else "partial",
        f"risk_policy_valid={pieces[0]}, circuit_breakers={pieces[1]}, data_quality_pass={pieces[2]}, safety_state={pieces[3]}",
        "Keep risk-first design: max loss/day/week, exposure caps, kill-switch drills, slippage/liquidity checks, and paper/live reconciliation.",
    )


def _explainability_dimension(counts: dict) -> dict:
    total = counts.get("signal_ledger_resolved", 0)
    replay = counts.get("signal_ledger_replay", 0)
    journal = REPORTS / "journal" / "trade_journal.jsonl"
    events = REPORTS / "journal" / "events.jsonl"
    journal_lines = 0
    for p in (journal, events):
        try:
            journal_lines += len([ln for ln in p.read_text().splitlines() if ln.strip()])
        except Exception:
            pass
    score = 30 * (total > 0) + 25 * (journal_lines > 0) + 20 * (replay < total if total else False) + 25 * (events.exists())
    return score_dimension(
        "Explainability and audit trail", score, "pass" if score >= 80 else "partial",
        f"resolved_signals={total}, replay_signals={replay}, journal_events={journal_lines}",
        "For every recommendation store thesis, bear case, invalidation, data timestamp, score breakdown, rejection reason, and post-trade review.",
    )


def _automation_dimension() -> dict:
    scripts = [ROOT / "loops" / "premarket_briefing.py", ROOT / "loops" / "eod_close.py",
               ROOT / "loops" / "reflection_weekly.py", ROOT / "ops" / "serve.py"]
    present = sum(p.exists() for p in scripts)
    reports = [REPORTS / "realtime-picks-latest.json", REPORTS / "allocation.json", REPORTS / "alerts.jsonl"]
    report_present = sum(p.exists() for p in reports)
    score = (present / len(scripts)) * 60 + (report_present / len(reports)) * 40
    return score_dimension(
        "Automation reliability", score, "pass" if score >= 80 else "partial",
        f"loop_scripts={present}/{len(scripts)}, operational_reports={report_present}/{len(reports)}",
        "Schedule market-day premarket/EOD/weekly paper loops via Hermes cron, with Telegram summaries and quiet failure alerts.",
    )


def _validation_dimension() -> dict:
    g = _load_report("gauntlet.json")
    val = _load_report("validate.json")
    mc = _load_report("monte-carlo.json")
    score = float(g.get("overall_score", 0) or 0)
    if val.get("pass"):
        score = min(100, score + 5)
    if "risk_of_ruin" in mc:
        score = min(100, score + 5)
    return score_dimension(
        "Validation rigor", score, "pass" if score >= 85 else ("partial" if score >= 60 else "fail"),
        f"gauntlet_score={g.get('overall_score')}, gauntlet_verdict={g.get('verdict')}, no_lookahead_pass={val.get('pass')}, monte_carlo_present={'risk_of_ruin' in mc}",
        "Push gauntlet above 85 with walk-forward stability, DSR/PBO improvements, slippage stress, and benchmark comparisons after costs.",
    )


def _governance_dimension() -> dict:
    gl = _load_report("go-live.json")
    verdict = gl.get("verdict", "UNKNOWN")
    gates = gl.get("gates", []) or []
    pass_count = sum(1 for g in gates if g.get("status") == "PASS")
    score = 100 if verdict == "CLEARED FOR LIVE" else min(90, 20 + pass_count * 10)
    return score_dimension(
        "Live safety governance", score, "pass" if verdict == "CLEARED FOR LIVE" else "partial",
        f"go_live_verdict={verdict}, gates_passing={pass_count}/{len(gates)}",
        "Keep live disabled until all gates are green, human signoff is bound to a report hash, and a tiny-size pilot is explicitly approved.",
    )


def evaluate() -> dict:
    counts = _table_counts()
    dimensions = []
    hard_blockers = []

    dim, blocked = _data_dimension(counts)
    dimensions.append(dim)
    if blocked:
        hard_blockers.append("survivorship_free_data")

    dim, blocked = _paper_dimension(counts)
    dimensions.append(dim)
    if blocked:
        hard_blockers.append("forward_paper_record")

    dimensions.extend([
        _benchmark_dimension(),
        _risk_dimension(),
        _explainability_dimension(counts),
        _automation_dimension(),
        _validation_dimension(),
        _governance_dimension(),
    ])

    weight_sum = sum(d["weight_pct"] for d in dimensions) or 1
    overall = round(sum(d["score"] * d["weight_pct"] for d in dimensions) / weight_sum, 1)
    if hard_blockers:
        verdict = "RESEARCH_ONLY"
    elif overall >= 85:
        verdict = "WORLD_CLASS_CANDIDATE"
    else:
        verdict = "IMPROVING"

    action_by_name = {d["name"]: d["action"] for d in dimensions}
    priority_actions = [
        action_by_name["Forward paper record"],
        action_by_name["Survivorship-free data"],
        action_by_name["Benchmark-adjusted edge"],
        action_by_name["Validation rigor"],
        action_by_name["Automation reliability"],
    ]

    return {
        "asof": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "overall_score": overall,
        "rating_1_to_10": round(overall / 10.0, 1),
        "hard_blockers": hard_blockers,
        "counts": counts,
        "dimensions": dimensions,
        "priority_actions": priority_actions,
        "disclaimer": "Informational engineering readiness audit, not financial advice. Markets risk loss of capital.",
    }


def render(report: dict) -> str:
    lines = [
        f"# TradingBrain World-Class Readiness — {report['verdict']}",
        f"_{report['asof']} · score {report['overall_score']}/100 · rating {report['rating_1_to_10']}/10_",
        "",
        "This audit measures whether TradingBrain has the evidence and operational controls expected of a world-class quant stock recommender.",
        "It does not certify profitability and is not financial advice.",
        "",
        "## Hard blockers",
    ]
    if report["hard_blockers"]:
        lines.extend(f"- {b.replace('_', ' ')}" for b in report["hard_blockers"])
    else:
        lines.append("- none")
    lines += ["", "## Dimensions"]
    for d in report["dimensions"]:
        lines.append(f"- **{d['name']}**: {d['score']}/100 ({d['status']}) — {d['evidence']}")
    lines += ["", "## Priority actions"]
    lines.extend(f"{i}. {a}" for i, a in enumerate(report["priority_actions"], 1))
    lines += ["", f"_{report['disclaimer']}_"]
    return "\n".join(lines)


def write_reports(report: dict | None = None) -> dict[str, Path]:
    REPORTS.mkdir(parents=True, exist_ok=True)
    report = report or evaluate()
    OUT_JSON.write_text(json.dumps(report, indent=2, default=str))
    OUT_MD.write_text(render(report))
    return {"json": OUT_JSON, "markdown": OUT_MD}


def main() -> None:
    report = evaluate()
    write_reports(report)
    print(json.dumps(report, indent=2, default=str) if "--json" in sys.argv else render(report))


if __name__ == "__main__":
    main()
