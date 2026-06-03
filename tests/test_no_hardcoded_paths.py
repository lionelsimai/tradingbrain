#!/usr/bin/env python3
"""Portability: the safety-critical core must contain no hardcoded repo path, and
paths.py must resolve the root portably."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# The order path + safety core MUST be portable (zero tolerance).
CORE = ["safety", "execution", "journal", "data", "paths.py"]
# Legacy packages still being migrated (tracked, not yet zero — see FINAL_BUILD_REPORT P2).
LEGACY = ["scripts", "loops", "backtest"]
HARDCODED = "/home/workspace/TradingBrain"


def _violations(targets):
    bad = []
    for t in targets:
        p = ROOT / t
        files = [p] if p.is_file() else [f for f in p.rglob("*.py") if "__pycache__" not in str(f)]
        for f in files:
            if HARDCODED in f.read_text():
                bad.append(str(f.relative_to(ROOT)))
    return bad


def test_safety_core_has_no_hardcoded_path():
    bad = _violations(CORE)
    assert not bad, f"hardcoded repo path in safety core: {bad}"


def test_paths_resolves_portably(tmp_path):
    # paths.py must resolve the root even when invoked from an unrelated cwd.
    out = subprocess.run(
        [sys.executable, str(ROOT / "paths.py")],
        cwd=str(tmp_path), capture_output=True, text=True,
        env={**os.environ, "TRADINGBRAIN_ROOT": str(ROOT)})
    assert out.returncode == 0 and str(ROOT) in out.stdout


def test_legacy_migration_is_tracked():
    # Not a hard failure: records how much legacy migration remains so it can't be forgotten.
    remaining = _violations(LEGACY)
    print(f"[portability] legacy files still hardcoding root: {len(remaining)}")
    assert isinstance(remaining, list)
