#!/usr/bin/env python3
"""Paper-only 24/7 runner for TradingBrain.

Keeps the system alive on any host (Railway, Fly, Render, a VPS) so it can
accumulate REAL paper fills and run its self-improvement review on a cadence.

SAFETY (do not weaken):
  * PAPER ONLY — never enables live trading, never pushes code anywhere.
  * Live stays fail-closed (refuses to start if live flags are set).
  * Every step is best-effort: a failing data fetch is logged, never fatal.

Env:
  TICK_SECONDS        seconds between paper cycles            (default 3600)
  REVIEW_EVERY_TICKS  run the improvement review every N ticks (default 24)

CLI:
  python3 ops/serve.py          # run forever
  python3 ops/serve.py --once   # one cycle then exit (good for cron)
"""
from __future__ import annotations
import os, subprocess, sys, time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TICK = int(os.environ.get("TICK_SECONDS", "3600"))
REVIEW_EVERY = int(os.environ.get("REVIEW_EVERY_TICKS", "24"))
PY = sys.executable

# Paper-trading pipeline (best-effort). Edit to match your preferred loop.
PAPER_PIPELINE = [
    [PY, "-m", "loops.signal_tracker", "emit"],
    [PY, "-m", "loops.signal_tracker", "resolve"],
    [PY, "-m", "loops.signal_tracker", "scorecard"],
    [PY, "-m", "scripts.brain.regime_label", "--backfill"],
    [PY, "-m", "scripts.recommend"],
    [PY, "-m", "scripts.export_app"],
    [PY, "-m", "loops.reconcile"],
]
# Validation pack refreshed periodically so the go-live verdict stays current.
REVIEW = [PY, "-m", "loops.improve", "review"]
VALIDATION = [
    [PY, "-m", "backtest.monte_carlo", "--paths", "20000", "--method", "block"],
    [PY, "-m", "lab.gauntlet"],
    [PY, "-m", "lab.go_live"],
]


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat()}] {msg}", flush=True)


def _run(cmd: list[str]) -> None:
    try:
        r = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, timeout=1800)
        _log(f"{' '.join(cmd[-2:])} -> {'ok' if r.returncode == 0 else f'exit {r.returncode}'}")
    except Exception as e:
        _log(f"{' '.join(cmd[-2:])} -> SKIPPED ({type(e).__name__})")


def cycle(n: int) -> None:
    _log(f"--- paper cycle {n} (mode=paper, live=OFF) ---")
    for cmd in PAPER_PIPELINE:
        _run(cmd)
    if n % REVIEW_EVERY == 0:
        _run(REVIEW)
        for cmd in VALIDATION:
            _run(cmd)


def main() -> None:
    if (os.environ.get("HERMES_TRADING_MODE", "paper") != "paper"
            or os.environ.get("TB_ALLOW_LIVE") in ("1", "true")):
        _log("REFUSING TO START: this runner is paper-only. Unset live flags.")
        sys.exit(1)
    once = "--once" in sys.argv
    _run(REVIEW)               # always boot with a fresh review
    n = 1
    while True:
        cycle(n)
        if once:
            _log("single cycle done (--once).")
            return
        n += 1
        time.sleep(TICK)


if __name__ == "__main__":
    main()
