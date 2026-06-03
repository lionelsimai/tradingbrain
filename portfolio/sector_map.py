#!/usr/bin/env python3
"""Symbol -> category ("sector") map from config/universe.yaml.

FIX-1 (P0-3): the order manager uses this to give portfolio constraints real
sector data, so the sector-exposure and correlated-cluster caps actually bind on
the submit path (previously the PortfolioState had an empty sector_map, so those
caps could never fire). Categories match portfolio/correlation.py's grouping so
the sector cap and the correlation cluster cap agree on what's "the same bet".
"""
from __future__ import annotations
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import CONFIG_DIR


@lru_cache(maxsize=1)
def load() -> dict:
    """Return {SYMBOL: category}. Empty dict if universe.yaml is missing."""
    import yaml
    f = CONFIG_DIR / "universe.yaml"
    out: dict[str, str] = {}
    if f.exists():
        u = yaml.safe_load(f.read_text()) or {}
        for cat, items in (u.get("universe", u) or {}).items():
            if isinstance(items, list):
                for t in items:
                    out[str(t).upper()] = str(cat)
    return dict(out)


def sector_of(symbol: str) -> str | None:
    return load().get(str(symbol).upper())
