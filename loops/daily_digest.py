#!/usr/bin/env python3
"""Daily loop: ingest fresh data → re-score signals → run brain → send digest.

Designed to be invoked by a scheduled automation each weekday morning.
Sends the markdown digest via Telegram + email (best-effort) and persists it.
"""
from __future__ import annotations
import argparse, subprocess, sys
from datetime import date
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
REPORTS = ROOT / "reports"
PY = sys.executable


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=900)
    return p.returncode, (p.stdout + p.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-ingest", action="store_true", help="Use existing data; just re-run brain")
    ap.add_argument("--ingest-edgar", action="store_true", help="Also pull EDGAR (slower)")
    args = ap.parse_args()

    steps = []
    if not args.skip_ingest:
        steps.extend([
            [PY, "-m", "scripts.backfill_10y", "--years", "1"],     # prices
            [PY, "-m", "scripts.ingest.macro"],                     # macro
            [PY, "-m", "scripts.ingest.fundamentals"],              # value/quality inputs
            [PY, "-m", "scripts.ingest.news"],                      # RSS + per-ticker
        ])
        if args.ingest_edgar:
            steps.append([PY, "-m", "scripts.ingest.edgar", "--form4-only"])
        steps.append([PY, "scripts/embed.py"])
        steps.append([PY, "scripts/build_fts.py"])

    steps.extend([
        [PY, "scripts/momentum.py"],                                 # quant momentum
        [PY, "-m", "scripts.signals.value_quality"],                 # value+quality signal
        [PY, "-m", "scripts.signals.events"],                        # insider+news burst
        [PY, "-m", "scripts.brain.decide", "--top", "20"],           # the brain
        [PY, "-m", "scripts.brain.compile_pages"],                   # GBrain compiled-truth pages
        [PY, "-m", "scripts.brain.entity_graph"],                    # self-wiring co-mention edges
        [PY, "-m", "scripts.brain.compile_sectors"],
    ])

    for cmd in steps:
        rc, out = run(cmd)
        print(f"\n$ {' '.join(cmd)}\n{out[-400:] if rc == 0 else out[-1500:]}")
        if rc != 0:
            print(f"  ⚠ step failed (rc={rc})")

    digest = REPORTS / f"{date.today()}-digest.md"
    if digest.exists():
        text = digest.read_text()
        print(f"\n=== DIGEST ({digest}) ===\n")
        print(text)
        return text
    return None


if __name__ == "__main__":
    main()
