#!/usr/bin/env python3
"""Portable path resolution — no hardcoded absolute repo root.

Resolution order:
  1. $TRADINGBRAIN_ROOT if set and valid
  2. walk up from this file until a repo marker (DOCTRINE.md / config/) is found
  3. fall back to this file's directory

Exposes ROOT + standard subdirs. Creates non-critical dirs; fails loudly if a
core dir (config/, data/) is missing so misconfiguration is obvious, not silent.

CLI: python3 paths.py    (prints the resolved layout)
"""
from __future__ import annotations
import os
from pathlib import Path

_MARKERS = ("DOCTRINE.md", "config", "paths.py")


def _looks_like_root(p: Path) -> bool:
    hits = sum((p / m).exists() for m in _MARKERS)
    return hits >= 2


def find_root() -> Path:
    env = os.environ.get("TRADINGBRAIN_ROOT")
    if env:
        p = Path(env).expanduser().resolve()
        if p.is_dir():
            return p
        raise SystemExit(f"TRADINGBRAIN_ROOT={env} is not a directory")
    here = Path(__file__).resolve().parent
    for cand in (here, *here.parents):
        if _looks_like_root(cand):
            return cand
    return here


ROOT = find_root()
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
LOGS_DIR = ROOT / "reports" / "logs"
DB_DIR = ROOT / "data"
DOCS_DIR = ROOT / "docs"
JOURNAL_DIR = ROOT / "reports" / "journal"

PRICES_DB = DATA_DIR / "prices.duckdb"
KNOWLEDGE_DB = DATA_DIR / "knowledge.duckdb"

_CORE = {"config": CONFIG_DIR, "data": DATA_DIR}
_CREATE = [REPORTS_DIR, LOGS_DIR, JOURNAL_DIR]


def ensure() -> None:
    missing = [name for name, p in _CORE.items() if not p.is_dir()]
    if missing:
        raise SystemExit(f"Core directories missing under {ROOT}: {missing}")
    for d in _CREATE:
        d.mkdir(parents=True, exist_ok=True)


ensure()


if __name__ == "__main__":
    print(f"ROOT        {ROOT}")
    for k in ("CONFIG_DIR", "DATA_DIR", "REPORTS_DIR", "LOGS_DIR", "DB_DIR",
              "DOCS_DIR", "JOURNAL_DIR", "PRICES_DB", "KNOWLEDGE_DB"):
        print(f"{k:12} {globals()[k]}")
