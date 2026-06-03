#!/usr/bin/env python3
"""The Orchestrator (the Chief) — DOCTRINE v3 Part XIII master cycle.

Directs specialists, integrates their structured briefs, rules Deploy/Iterate/
Reject, writes lessons + strategy status + failures to memory, updates the
playbook, and emits a Decision Dossier. Budget-disciplined: reads existing
validation artifacts unless --retrain is passed (re-running 30y backtests every
cycle is waste, not rigor — Part X diminishing-returns stop).

Specialists wired in:
  Quant/Backtest  -> backtest.research_engine  (research-report.json)
  Simulation      -> backtest.stress_test       (calibration.json / stress-test.json)
  Red Team        -> collective.review.red_team
  Risk Officer    -> collective.review.risk_officer
  Memory Librarian-> collective.memory
  Meta-Learner    -> distill() below
"""
from __future__ import annotations
import json, subprocess, sys, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
RESEARCH = ROOT / "reports" / "research-report.json"
PLAYBOOK = ROOT / "PLAYBOOK.md"
DOSSIER = ROOT / "reports" / "decision-dossier.md"

sys.path.insert(0, str(ROOT))
from scripts.collective import memory, review

def _load_research():
    return json.loads(RESEARCH.read_text()) if RESEARCH.exists() else {}

def retrain(budget_note=""):
    """Run the heavy specialists (Quant + Simulation). Only when explicitly asked."""
    for mod in ["backtest.stress_test", "backtest.research_engine"]:
        print(f"  [orchestrator] running {mod} ...", flush=True)
        subprocess.run([sys.executable, "-m", mod], cwd=str(ROOT), timeout=1200,
                       capture_output=True)

def distill(cycle_id, research, decisions) -> list[str]:
    """Meta-Learner: write durable lessons from this cycle's evidence."""
    lessons = []
    sf = research.get("survivorship_free", False)
    if not sf:
        lid = memory.add_lesson(cycle_id,
            "Universe is survivorship-biased; treat all backtest edges as INDICATIVE and "
            "discount live expectations until point-in-time delisted data is sourced.",
            category="data_integrity", confidence=0.9)
        lessons.append("data_integrity: results are indicative, not validated")
    for setup, d in decisions.items():
        rt = d["red_team"]
        # Failures / wounds become failure_log + lessons
        if rt["verdict"] in ("WOUNDED", "KILLED"):
            for f in rt["findings"]:
                lid = memory.add_lesson(cycle_id, f"{setup}: {f}", category="red_team",
                                        evidence=rt["verdict"], confidence=0.7)
                memory.log_failure(cycle_id, setup, f, source="red_team", lesson_id=lid)
            lessons.append(f"{setup}: red-team {rt['verdict'].lower()} ({rt['severity']})")
        # Regime-specific negative expectancy → durable lesson
        byr = research.get("strategies", {}).get(setup, {}).get("by_regime", {})
        neg = [k for k,v in byr.items() if isinstance(v,dict) and v.get("expectancy_R",0) <= 0]
        if neg:
            memory.add_lesson(cycle_id,
                f"{setup} has non-positive expectancy in regimes {neg}; gate it off there.",
                category="regime", evidence=str({k:byr[k].get('expectancy_R') for k in neg}),
                confidence=0.75)
    return lessons

def decide(setup, research) -> dict:
    """Integrate specialist briefs into a final ruling. Red Team + Risk Officer can veto."""
    s = research.get("strategies", {}).get(setup, {})
    eng_verdict = s.get("verdict", "Unknown")
    rt = review.red_team(setup)
    ro = review.risk_officer(setup)
    # Integration rule: start from engine verdict, then apply vetoes.
    ruling = eng_verdict
    if ro["verdict"] == "VETO" or rt["verdict"] == "KILLED":
        ruling = "Reject"
    elif rt["verdict"] == "WOUNDED" and ruling == "Deploy":
        ruling = "Iterate"   # downgrade: survived but flawed
    return {"setup": setup, "engine_verdict": eng_verdict, "ruling": ruling,
            "red_team": rt, "risk_officer": ro,
            "oos": s.get("out_of_sample", {}).get("expectancy_R")
                   if isinstance(s.get("out_of_sample"), dict) else s.get("oos_exp")}

def run_cycle(do_retrain=False, budget_tokens=0, harden=True):
    cycle_id = "cyc_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    t0 = time.time()
    print(f"═══ Orchestrator cycle {cycle_id} ═══", flush=True)

    # 1. PLAN
    goals = ["Re-validate the strategy library and rule Deploy/Iterate/Reject",
             "Distill durable lessons from rejections/wounds into memory",
             "Refresh the playbook with current best practices + traps"]

    # 2. RETRIEVE
    prior = memory.retrieve(limit=10)
    print(f"  [memory] {memory.stats()} | {len(prior['lessons'])} prior lessons recalled", flush=True)

    # 3-6. RESEARCH / HYPOTHESIZE / BACKTEST / SIMULATE (heavy — only on retrain)
    if do_retrain:
        retrain()
    research = _load_research()
    if not research:
        print("  No research-report.json — run with --retrain first."); return

    # 7-8. RED-TEAM + RISK-REVIEW + DECIDE
    decisions = {}
    for setup in research.get("strategies", {}):
        decisions[setup] = decide(setup, research)
        d = decisions[setup]
        memory.record_episode(cycle_id, "orchestrator", f"rule {setup}",
            result={"ruling": d["ruling"], "red_team": d["red_team"]["verdict"],
                    "risk": d["risk_officer"]["verdict"]}, decision=d["ruling"])
        memory.upsert_strategy(setup,
            status=("validated" if d["ruling"]=="Deploy" else
                    "provisional" if d["ruling"]=="Iterate" else "rejected"),
            verdict=d["ruling"], oos_expectancy_R=d["oos"],
            red_team_findings="; ".join(d["red_team"]["findings"]),
            risk_officer_verdict=d["risk_officer"]["verdict"])

    # 9-10. DISTILL + UPDATE
    lessons = distill(cycle_id, research, decisions)
    write_playbook(cycle_id, research, decisions)

    # 11. REPORT
    spent = time.time() - t0
    write_dossier(cycle_id, goals, research, decisions, lessons, spent)
    print(f"  [done] {len(decisions)} strategies ruled · {len(lessons)} lessons · {spent:.1f}s")

    # 12. HARDEN — bounded self-improvement pass on the single highest-stakes
    # output (the dossier). Deep compute where it changes the answer (Part IX),
    # budget-capped so it converges not spins (Part VI).
    if harden:
        try:
            # Optional external self-improve engine. Resolve portably: env var
            # SELF_IMPROVE_ENGINE, else skip cleanly (never hardcode a machine path).
            import os
            engine = os.environ.get("SELF_IMPROVE_ENGINE")
            if not engine or not Path(engine).exists():
                print("  [harden] skipped (no SELF_IMPROVE_ENGINE configured).", flush=True)
                raise FileNotFoundError("self-improve engine not configured")
            print("  [harden] self-improve pass on dossier (budget: 6 calls / 3 iters)...", flush=True)
            r = subprocess.run(
                [sys.executable, engine, "improve",
                 "--input", str(DOSSIER), "--output", str(DOSSIER),
                 "--task", "Sharpen a swing-trading research decision dossier for a founder operator",
                 "--criteria", "Accurate to the rulings table; states the single biggest risk; "
                 "honest about survivorship/INDICATIVE status; concise; no fabricated numbers or verdicts",
                 "--max-iters", "3", "--max-calls", "6", "--target-score", "88", "--quiet"],
                cwd=ROOT, timeout=600, capture_output=True, text=True)
            out = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
            if out:
                print(f"  [harden] {out.get('stop_reason','done')} · "
                      f"best {out.get('best_score')} · trajectory {out.get('trajectory')}", flush=True)
        except Exception as e:
            print(f"  [harden] skipped: {e}", flush=True)

    print(f"  Dossier → {DOSSIER}")
    return cycle_id

def write_playbook(cycle_id, research, decisions):
    deploy = [s for s,d in decisions.items() if d["ruling"]=="Deploy"]
    iterate = [s for s,d in decisions.items() if d["ruling"]=="Iterate"]
    reject = [s for s,d in decisions.items() if d["ruling"]=="Reject"]
    mem = memory.retrieve(limit=12)
    lines = ["# TradingBrain Collective — Playbook",
        f"\n> The living record of the org getting smarter. Updated each cycle. Last: {cycle_id}.",
        "\n## Deployable strategies (trade live, full size)"]
    lines += [f"- **{s}** — OOS {decisions[s]['oos']}R · risk {decisions[s]['risk_officer']['verdict']}" for s in deploy] or ["- (none)"]
    lines += ["\n## Provisional (Iterate — half size, flawed)"]
    lines += [f"- **{s}** — {decisions[s]['red_team']['verdict']}: {decisions[s]['red_team']['findings'][0]}" for s in iterate] or ["- (none)"]
    lines += ["\n## Rejected / dead ideas (do not re-test without new conditions)"]
    lines += [f"- **{s}** — {decisions[s]['ruling']}" for s in reject] or ["- (none)"]
    lines += ["\n## Known traps (top reinforced lessons)"]
    lines += [f"- _{l['category']}_: {l['lesson']} (×{l['reinforced']})" for l in mem["lessons"][:10]] or ["- (none yet)"]
    lines += [f"\n## Data integrity\n- Survivorship-bias-free: **{research.get('survivorship_free', False)}** → "
              f"results are {'VALIDATED' if research.get('survivorship_free') else '**INDICATIVE only**'}."]
    PLAYBOOK.write_text("\n".join(lines) + "\n")

def write_dossier(cycle_id, goals, research, decisions, lessons, spent):
    L = [f"# Decision Dossier — {cycle_id}",
         f"\n_Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC} · compute {spent:.1f}s · "
         f"data {'survivorship-free' if research.get('survivorship_free') else 'INDICATIVE (survivorship-biased)'}_",
         "\n## Goals", *[f"- {g}" for g in goals],
         "\n## Rulings (engine → after Red Team + Risk Officer)",
         "\n| Strategy | Engine | Red Team | Risk Officer | **Final** |",
         "|---|---|---|---|---|"]
    for s,d in decisions.items():
        L.append(f"| {s} | {d['engine_verdict']} | {d['red_team']['verdict']} ({d['red_team']['severity']}) "
                 f"| {d['risk_officer']['verdict']} | **{d['ruling']}** |")
    L += ["\n## Red Team findings"]
    for s,d in decisions.items():
        L.append(f"- **{s}**: " + "; ".join(d["red_team"]["findings"]))
    L += ["\n## Lessons distilled this cycle"]
    L += [f"- {x}" for x in lessons] if lessons else ["- (none)"]
    L += ["\n## Biggest risk to these conclusions",
          "- Survivorship-biased universe: live edge is likely lower than shown. "
          "Treat all rulings as INDICATIVE until point-in-time delisted-universe data is sourced."]
    DOSSIER.write_text("\n".join(L) + "\n")

if __name__ == "__main__":
    do_retrain = "--retrain" in sys.argv
    harden = "--no-harden" not in sys.argv
    run_cycle(do_retrain=do_retrain, harden=harden)
