#!/usr/bin/env python3
"""Tests for experience-grounded memory recall (the memory upgrade).

Guards the three properties the memory master prompt demands:
  * recall surfaces real resolved-trade experience (coverage),
  * recalled quantitative facts are honestly labeled (n + replay/live source),
  * recall never fabricates — every example cites a real signal id,
  * the legacy retrieve() still works (backward compatibility).
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import duckdb
from collective import memory
from paths import ROOT as PROOT

KB = PROOT / "data" / "knowledge.duckdb"


def _a_resolved_setup():
    con = duckdb.connect(str(KB))
    row = con.execute(
        "SELECT setup FROM signal_ledger WHERE realized_R IS NOT NULL AND setup IS NOT NULL "
        "GROUP BY setup ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    con.close()
    return row[0] if row else None


def test_recall_exists():
    assert hasattr(memory, "recall"), "memory.recall() must exist"


def test_recall_surfaces_experience():
    s = _a_resolved_setup()
    if not s:
        return
    out = memory.recall(s)
    assert out["experience"], "recall must surface resolved-trade experience"
    assert out["experience"][0]["n"] > 0


def test_recalled_facts_are_honestly_labeled():
    """Every quantitative experience fact must carry a sample size and a source label."""
    s = _a_resolved_setup()
    if not s:
        return
    for e in memory.recall(s)["experience"]:
        assert e.get("n") is not None
        assert e.get("source")
        assert e.get("source_label")  # replay vs live, never conflated


def test_recall_never_fabricates_examples():
    """Cited example signal ids must actually exist in the ledger."""
    s = _a_resolved_setup()
    if not s:
        return
    out = memory.recall(s)
    con = duckdb.connect(str(KB))
    for ex in out["examples"]:
        hit = con.execute("SELECT COUNT(*) FROM signal_ledger WHERE id = ?",
                          [ex["signal_id"]]).fetchone()[0]
        assert hit == 1, f"recalled a non-existent signal id: {ex['signal_id']}"
    con.close()


def test_legacy_retrieve_still_works():
    out = memory.retrieve(limit=5)
    assert "lessons" in out  # backward compatibility preserved
