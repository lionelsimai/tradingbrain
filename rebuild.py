#!/usr/bin/env python3
"""One command to rebuild the entire research instrument, deterministically, in
dependency order — and prove it. This is what makes the brain a *reproducible*
instrument: every number in reports/ is traceable to the exact code+data that
produced it, recorded in reports/MANIFEST.json.

Pipeline (each step gated on the previous):
  0. validate   — no-look-ahead proof + live==backtest + determinism
  1. data_quality — point-in-time price sanity gate (hard-fail stops the build)
  2. stress_test  — calibration.json (setup x regime edge, net of costs)
  3. research     — research-report.json (full lifecycle + PBO/DSR)
  4. signal replay — backfill + resolve + scorecard (live-vs-backtest drift)
  5. reconcile     — strategy_library status + lessons
  6. provenance    — hash code+data, write MANIFEST.json

Usage:
  python3 rebuild.py                 # full deterministic rebuild
  python3 rebuild.py --fast          # skip the slow research lifecycle
  python3 rebuild.py --seed 7        # set global RNG seed (default 1)
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
REPORTS = ROOT / "reports"


def run(label: str, cmd: list[str], gate: bool = True) -> dict:
    t0 = time.time()
    print(f"\n=== {label} ===", flush=True)
    env = dict(os.environ)
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    dt = round(time.time() - t0, 1)
    ok = proc.returncode == 0
    status = "OK" if ok else f"FAIL (rc={proc.returncode})"
    print(f"--- {label}: {status} in {dt}s", flush=True)
    if gate and not ok:
        print(f"\nBUILD HALTED: {label} failed (gating step).", flush=True)
        sys.exit(proc.returncode)
    return {"step": label, "ok": ok, "seconds": dt, "cmd": " ".join(cmd)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="skip the slow research lifecycle")
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()

    os.environ["TB_SEED"] = str(a.seed)
    py = sys.executable
    steps = []
    t0 = time.time()

    # 0. correctness proofs (gate the whole build)
    steps.append(run("validate (no-look-ahead / live==backtest / determinism)",
                     [py, "-m", "lab.validate"]))
    # 1. data quality gate
    steps.append(run("data_quality", [py, "-m", "lab.data_quality"]))
    # 2. calibration
    steps.append(run("stress_test -> calibration.json", [py, "-m", "backtest.stress_test"]))
    # 3. research lifecycle (slow)
    if not a.fast:
        steps.append(run("research_engine --all -> research-report.json",
                         [py, "-m", "backtest.research_engine", "--all"]))
    # 4. live-vs-backtest replay scorecard
    steps.append(run("signal replay backfill", [py, "-m", "loops.signal_tracker", "backfill"]))
    steps.append(run("signal resolve", [py, "-m", "loops.signal_tracker", "resolve"]))
    steps.append(run("scorecard", [py, "-m", "loops.signal_tracker", "scorecard"]))
    # 5. reconcile the loop
    steps.append(run("reconcile", [py, "-m", "loops.reconcile"], gate=False))
    # 6. provenance manifest (records hashes + key results)
    steps.append(run("provenance -> MANIFEST.json", [py, "-m", "lab.provenance"], gate=False))

    total = round(time.time() - t0, 1)
    summary = {"rebuild_seconds": total, "seed": a.seed, "fast": a.fast, "steps": steps}
    (REPORTS / "rebuild-summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n=== REBUILD COMPLETE in {total}s — all gating steps passed ===")
    print("    reports/MANIFEST.json + reports/rebuild-summary.json written")


if __name__ == "__main__":
    main()
