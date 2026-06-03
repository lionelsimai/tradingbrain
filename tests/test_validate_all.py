#!/usr/bin/env python3
"""Light test for the one-command validator (no recursive pytest)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import validate_all


def test_safety_invariants_run_and_pass():
    results = validate_all.check_safety_invariants()
    assert len(results) >= 5
    by = {r["name"]: r for r in results}
    # the core honesty invariants must hold in this repo state
    assert by["Conviction cap (no overclaiming)"]["ok"]
    assert by["App export bridge"]["ok"]
    assert by["Go-live verdict + live enforcement"]["ok"]


def test_writes_final_report(tmp_path, monkeypatch):
    results = validate_all.check_safety_invariants()
    validate_all.write_final_report(results)
    assert validate_all.REPORT_MD.exists()
    txt = validate_all.REPORT_MD.read_text()
    assert "not cleared to trade real money" in txt  # honesty is in the report
