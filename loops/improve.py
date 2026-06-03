#!/usr/bin/env python3
"""TradingBrain — Self-Improvement Cycle (the disciplined spine).

Turns the existing research/scorecard machinery into a closed, scientific loop:

    score current state vs the LOCKED goal  ->  classify toward-goal / toward-failure
    ->  propose EXACTLY ONE change (logged with hypothesis + expected effect)
    ->  keep / revert on the next cycle  ->  repeat.

Design rules (self-improving-agent doctrine):
  * ACCURATE   — reads real report fields; flags any metric it cannot verify.
  * RELIABLE   — pure-read, idempotent per day, never crashes on a missing report.
  * GOAL       — every result is scored against config/goal.yaml (success/failure).
  * SELF-IMPROVING — one variable per cycle, tracked in export-state/experiments.csv.
  * SAFE       — READ-ONLY by default. Proposes; never executes or flips to live.

CLI:
  python3 -m loops.improve review        # run a cycle, print + write the review
  python3 -m loops.improve experiments   # show the single-variable changelog
  python3 -m loops.improve resolve <id> kept|reverted ["note"]
"""
from __future__ import annotations
import argparse, csv, json, sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from paths import ROOT, REPORTS_DIR, CONFIG_DIR

EXPORT = ROOT / "export-state"
EXPERIMENTS = EXPORT / "experiments.csv"
REVIEW_MD = REPORTS_DIR / "improvement-review.md"
REVIEW_JSON = REPORTS_DIR / "improvement-review.json"
OPEN_STATES = {"proposed", "approved", "running"}
EXP_COLS = ["experiment_id", "opened_at", "cycle_id", "variable", "current_value",
            "proposed_value", "hypothesis", "expected_effect", "baseline_metric",
            "baseline_value", "status", "result_value", "decision", "decided_at", "notes"]


def _load_json(p: Path, default):
    try:
        return json.loads(p.read_text())
    except Exception:
        return default


def _load_yaml(p: Path) -> dict:
    try:
        import yaml
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


def _cycle_id() -> str:
    return "cyc_" + datetime.now(timezone.utc).strftime("%Y%m%d")


def _read_experiments() -> list[dict]:
    if not EXPERIMENTS.exists():
        return []
    with EXPERIMENTS.open() as f:
        return list(csv.DictReader(f))


def _write_experiments(rows: list[dict]) -> None:
    EXPORT.mkdir(parents=True, exist_ok=True)
    with EXPERIMENTS.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXP_COLS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in EXP_COLS})


def _open_experiment(rows: list[dict]) -> dict | None:
    for r in rows:
        if r.get("status") in OPEN_STATES:
            return r
    return None


# ---------------------------------------------------------------- scoring ----
def score_live(goal: dict, sc: dict) -> dict:
    """Score TRUE-live metrics against the goal. Replay/backtest is NOT scored
    here — only real fills count, per the goal's honesty rule."""
    succ = goal.get("success", {})
    live = sc.get("overall_live", {}) or {}
    n = int(live.get("n", 0) or 0)
    checks, metrics = [], {}

    if n == 0:
        return {
            "status": "INSUFFICIENT_DATA",
            "live_n": 0,
            "checks": [],
            "note": "0 true live fills. Scorecard is replay/backtest only — "
                    "not scored against the goal yet (would be dishonest).",
        }

    def chk(name, val, op, target):
        ok = (val >= target) if op == ">=" else (val <= target)
        checks.append({"metric": name, "value": val, "need": f"{op} {target}", "pass": ok})
        metrics[name] = val
        return ok

    passed = True
    passed &= chk("live_trades", n, ">=", succ.get("min_live_trades", 50))
    passed &= chk("expectancy_R", live.get("expectancy_R", 0), ">=", succ.get("min_expectancy_R", 0.05))
    passed &= chk("profit_factor", live.get("profit_factor", 0), ">=", succ.get("min_profit_factor", 1.3))
    passed &= chk("win_rate_pct", live.get("win_rate", 0), ">=", succ.get("min_win_rate_pct", 45))
    # drawdown & sharpe need a live equity curve we don't have from this file:
    checks.append({"metric": "max_drawdown_pct", "value": None,
                   "need": f"<= {succ.get('max_drawdown_pct', 20)}", "pass": None,
                   "note": "pending live equity curve"})
    checks.append({"metric": "sharpe", "value": None,
                   "need": f">= {succ.get('min_sharpe', 0.5)}", "pass": None,
                   "note": "pending live equity curve"})

    fail = goal.get("failure", {})
    failing = (live.get("expectancy_R", 0) < fail.get("expectancy_R_below", 0.0)
               and n >= fail.get("min_n_for_failure_call", 30))
    status = "FAILING" if failing else ("ON_TRACK" if passed else "TUNING")
    return {"status": status, "live_n": n, "checks": checks, "metrics": metrics}


def goal_realism(goal: dict) -> list[str]:
    """Embodies the doctrine's 'stop if the goal is unrealistic'. Evidence from
    the system's own portfolio backtest (FLAWS-AND-PROFIT): ~5-7% CAGR, Sharpe
    ~0.6, trails buy-and-hold in bull regimes."""
    succ = goal.get("success", {})
    w = []
    if succ.get("min_sharpe", 0) > 1.0:
        w.append(f"min_sharpe={succ['min_sharpe']} is above what the backtest "
                 "ever produced (~0.6). Likely unrealistic for this universe.")
    if not succ.get("not_worse_than_qqq_sharpe", True) is False:
        pass  # default (must not lose to QQQ risk-adjusted) is fine
    tgt = succ.get("min_cagr_pct")
    if tgt and tgt > 12:
        w.append(f"min_cagr_pct={tgt}% exceeds the system's proven ~5-7% CAGR. "
                 "A market-beating return target is not supported by the evidence.")
    if succ.get("beat_qqq_total_return"):
        w.append("Goal asks to beat QQQ on total return — the portfolio backtest "
                 "showed the opposite in every bull regime. Reframe to risk-adjusted.")
    return w


# ----------------------------------------------------- the single change ----
def propose_change(goal: dict, sc: dict, calib: dict, strat: list[dict],
                   realism: list[str]) -> dict:
    """Return the ONE highest-value next change, data-driven, in priority order."""
    succ = goal.get("success", {})
    live = sc.get("overall_live", {}) or {}
    n_live = int(live.get("n", 0) or 0)

    # 1) Can't tune on data we don't have. Accumulate real fills first.
    if n_live < succ.get("min_live_trades", 50):
        return {
            "variable": "data_mode",
            "current_value": f"replay-only (live n={n_live})",
            "proposed_value": "paper (accumulate real fills)",
            "hypothesis": "The +0.31R edge is from replay over recent, "
                          "survivorship-biased history; only true paper fills "
                          "can confirm it survives real execution and slippage.",
            "expected_effect": f"Reach >= {succ.get('min_live_trades', 50)} live "
                               "trades so the goal can actually be scored.",
            "baseline_metric": "live_trades",
            "baseline_value": n_live,
        }

    # 2) A setup is bleeding live -> demote that ONE setup.
    worst = None
    for s, d in (sc.get("by_setup", {}) or {}).items():
        if d.get("n", 0) >= 25 and d.get("expectancy_R", 0) < 0:
            if worst is None or d["expectancy_R"] < worst[1]["expectancy_R"]:
                worst = (s, d)
    if worst:
        s, d = worst
        return {
            "variable": f"strategy_status[{s}]",
            "current_value": "enabled",
            "proposed_value": "Broken (gate off)",
            "hypothesis": f"{s} expectancy is {d['expectancy_R']:+.3f}R live over "
                          f"n={d['n']} — the backtest edge has not held.",
            "expected_effect": "Removing the bleeding setup lifts overall live expectancy.",
            "baseline_metric": f"{s}_expectancy_R",
            "baseline_value": d.get("expectancy_R"),
        }

    # 3) An overfit flag is set -> tighten that ONE setup.
    for s, d in (calib.get("calibration", {}) or {}).items():
        if d.get("overfit_flag"):
            return {
                "variable": f"overfit[{s}]",
                "current_value": "enabled, overfit_flag=true",
                "proposed_value": "re-validate on a longer OOS window or disable",
                "hypothesis": f"{s} shows an overfit flag; its edge may be curve-fit.",
                "expected_effect": "More robust setup set; lower live drift.",
                "baseline_metric": f"{s}_oos_expectancy_R",
                "baseline_value": d.get("oos_expectancy_R"),
            }

    # 4) Goal itself looks unrealistic -> escalate to human (a goal change).
    if realism:
        return {
            "variable": "config/goal.yaml",
            "current_value": "current targets",
            "proposed_value": "reframe to a realistic, risk-adjusted goal",
            "hypothesis": "The goal exceeds what the evidence supports: " + realism[0],
            "expected_effect": "A goal the system can actually be judged against.",
            "baseline_metric": "goal_realism",
            "baseline_value": "unrealistic",
        }

    # 5) Default backlog: the next robustness fix (one item).
    return {
        "variable": "universe_liquidity_filter",
        "current_value": "all 77 names tradable",
        "proposed_value": "restrict to top names by $-volume",
        "hypothesis": "Thin tickers add slippage and un-exitable risk without edge.",
        "expected_effect": "Lower real-world costs; more reliable fills.",
        "baseline_metric": "tradable_names",
        "baseline_value": 77,
    }


def run_cycle() -> dict:
    goal = _load_yaml(CONFIG_DIR / "goal.yaml")
    sc = _load_json(REPORTS_DIR / "live-scorecard.json", {})
    calib = _load_json(REPORTS_DIR / "calibration.json", {})
    strat = []
    sl = EXPORT / "strategy_library.csv"
    if sl.exists():
        with sl.open() as f:
            strat = list(csv.DictReader(f))

    scored = score_live(goal, sc)
    realism = goal_realism(goal)
    rows = _read_experiments()
    open_exp = _open_experiment(rows)
    cid = _cycle_id()

    if open_exp:
        change = {"blocked_by_open_experiment": open_exp["experiment_id"],
                  "variable": open_exp["variable"]}
    else:
        change = propose_change(goal, sc, calib, strat, realism)
        # log it as 'proposed' (idempotent: one per cycle/day)
        if not any(r.get("cycle_id") == cid for r in rows):
            exp_id = f"exp_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            rows.append({
                "experiment_id": exp_id, "opened_at": datetime.now(timezone.utc).isoformat(),
                "cycle_id": cid, "variable": change["variable"],
                "current_value": change["current_value"], "proposed_value": change["proposed_value"],
                "hypothesis": change["hypothesis"], "expected_effect": change["expected_effect"],
                "baseline_metric": change["baseline_metric"], "baseline_value": change["baseline_value"],
                "status": "proposed", "result_value": "", "decision": "", "decided_at": "", "notes": "",
            })
            _write_experiments(rows)
            change["experiment_id"] = exp_id

    out = {
        "cycle_id": cid, "asof": datetime.now(timezone.utc).isoformat(),
        "mode": goal.get("mode", "read_only"), "objective": goal.get("objective", ""),
        "scored": scored, "goal_realism_warnings": realism,
        "proposed_change": change,
        "replay_context": sc.get("overall", {}),
    }
    REVIEW_JSON.write_text(json.dumps(out, indent=2, default=str))
    REVIEW_MD.write_text(render_review(out))
    return out


# ---------------------------------------------------------------- render ----
def render_review(o: dict) -> str:
    s = o["scored"]
    L = [f"# Self-Improvement Cycle — {o['cycle_id']}",
         f"_mode: **{o['mode']}** · {o['asof']}_", "",
         f"**Objective:** {o['objective']}", "",
         "## 1. Inputs used",
         f"- live scorecard, calibration, strategy library (true live fills: **{s.get('live_n', 0)}**)"]
    if s["status"] == "INSUFFICIENT_DATA":
        L.append(f"- ⚠ {s['note']}")
    rc = o.get("replay_context", {})
    if rc:
        L.append(f"- replay context (INDICATIVE ONLY, not scored): expectancy "
                 f"{rc.get('expectancy_R')}R, PF {rc.get('profit_factor')}, "
                 f"win {rc.get('win_rate')}%, n={rc.get('n')}")
    L += ["", "## 2. Outcome scored against the goal", f"- **Status: {s['status']}**"]
    for c in s.get("checks", []):
        mark = "✓" if c["pass"] else ("✗" if c["pass"] is False else "…")
        extra = f" ({c['note']})" if c.get("note") else ""
        L.append(f"  - {mark} {c['metric']}: {c['value']} (need {c['need']}){extra}")
    if o["goal_realism_warnings"]:
        L += ["", "## 2b. Goal realism check"]
        L += [f"  - ⚠ {w}" for w in o["goal_realism_warnings"]]
    ch = o["proposed_change"]
    L += ["", "## 3. Why this happened (hypothesis)"]
    L.append(f"- {ch.get('hypothesis', 'see open experiment')}")
    L += ["", "## 4. The ONE proposed change + expected effect"]
    if ch.get("blocked_by_open_experiment"):
        L.append(f"- An experiment is already open (`{ch['blocked_by_open_experiment']}`, "
                 f"variable `{ch['variable']}`). Per the single-variable rule, **resolve "
                 "it (keep/revert) before proposing the next change.**")
    else:
        L.append(f"- **Variable:** `{ch['variable']}`")
        L.append(f"- **Change:** {ch['current_value']} → {ch['proposed_value']}")
        L.append(f"- **Expected effect:** {ch['expected_effect']}")
        if ch.get("experiment_id"):
            L.append(f"- logged as `{ch['experiment_id']}` (status: proposed)")
    L += ["", "## 5. Baseline decision", "- baseline UNCHANGED — this cycle is read-only.",
          "", "## 6. Changelog", f"- see `export-state/experiments.csv`",
          "", "## 7. Approval gate",
          "- **No live action will be taken.** To proceed: review the change above, then "
          "either apply it manually or approve the experiment. Live trading stays OFF "
          "until you flip `mode` in `config/goal.yaml` and confirm."]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="TradingBrain self-improvement cycle")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("review")
    sub.add_parser("experiments")
    rp = sub.add_parser("resolve")
    rp.add_argument("experiment_id")
    rp.add_argument("decision", choices=["kept", "reverted"])
    rp.add_argument("note", nargs="?", default="")
    a = ap.parse_args()

    if a.cmd == "experiments":
        rows = _read_experiments()
        if not rows:
            print("No experiments logged yet.")
            return
        for r in rows:
            print(f"[{r['status']:9}] {r['experiment_id']}  {r['variable']}: "
                  f"{r['current_value']} -> {r['proposed_value']}  "
                  f"({r['decision'] or 'open'})")
        return

    if a.cmd == "resolve":
        rows = _read_experiments()
        # Verification (F7): capture the current headline edge and compare to the
        # baseline recorded when the experiment opened. A "kept" change that did
        # not improve the metric is tagged UNVERIFIED so the loop can't drift on
        # a label alone.
        sc = _load_json(REPORTS_DIR / "live-scorecard.json", {})
        live = sc.get("overall_live") or {}
        now_metric = live.get("expectancy_R")
        if now_metric is None:  # no live yet — fall back to replay, clearly noted
            now_metric = (sc.get("overall") or {}).get("expectancy_R")
            metric_src = "replay (no live yet)"
        else:
            metric_src = "live"
        hit = False
        for r in rows:
            if r["experiment_id"] == a.experiment_id:
                r["status"] = f"resolved-{a.decision}"
                r["decision"] = a.decision
                r["decided_at"] = datetime.now(timezone.utc).isoformat()
                note = a.note
                if a.decision == "kept":
                    r["result_value"] = f"{metric_src} expectancy_R={now_metric}"
                    # try numeric comparison against the baseline value if present
                    try:
                        base = float(str(r.get("baseline_value", "")).split("/")[0].strip())
                        if now_metric is not None and float(now_metric) <= base:
                            note = (note + " | UNVERIFIED: metric did not improve vs "
                                    f"baseline ({now_metric} <= {base}) — keep is on faith.").strip()
                    except Exception:
                        if metric_src.startswith("replay"):
                            note = (note + " | UNVERIFIED: no live metric to confirm "
                                    "improvement.").strip()
                r["notes"] = note
                hit = True
        if hit:
            _write_experiments(rows)
            print(f"Resolved {a.experiment_id}: {a.decision} "
                  f"(checked against {metric_src} expectancy_R={now_metric}).")
            print("Next cycle may now propose a new change.")
        else:
            print(f"No experiment {a.experiment_id}.")
        return

    # default: review
    o = run_cycle()
    print(REVIEW_MD.read_text())
    print(f"\n(wrote {REVIEW_MD.name} and {REVIEW_JSON.name} to reports/)")


if __name__ == "__main__":
    main()
