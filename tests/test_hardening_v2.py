#!/usr/bin/env python3
"""Tests for the v2 hardening pass: real regime labels, hard overfitting gate,
sign-off hash binding, regime-aware recall, and recall fidelity."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


# --- F9: real regime labels --------------------------------------------------
def test_regime_classifier_known_crashes():
    from scripts.brain.regime_label import regime_at
    assert regime_at("2020-03-16") == "crash"      # COVID
    assert regime_at("2008-10-10") == "crash"      # GFC
    assert regime_at("2021-06-15") in ("bull", "high_vol_bull")


def test_ledger_regime_is_no_longer_placeholder():
    import duckdb
    c = duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"))
    bad = c.execute("SELECT COUNT(*) FROM signal_ledger WHERE regime = 'replay'").fetchone()[0]
    real = c.execute("SELECT COUNT(DISTINCT regime) FROM signal_ledger").fetchone()[0]
    c.close()
    assert bad == 0, "signal_ledger.regime still contains the 'replay' placeholder"
    assert real >= 2, "expected multiple real regime labels"


# --- regime-aware recall -----------------------------------------------------
def test_recall_is_regime_aware():
    from collective import memory
    out = memory.recall("TREND_LEADER")
    assert out.get("experience_by_regime"), "recall must expose a per-regime breakdown"
    assert out.get("lessons_decayed") is True


# --- F8: non-circular fidelity ----------------------------------------------
def test_recall_fidelity_is_perfect():
    from lab.memory_metrics import recall_fidelity
    r = recall_fidelity()
    assert r["fidelity_pct"] == 100.0, "recall misreports the track record somewhere"


# --- F5: hard overfitting gate ----------------------------------------------
def test_overfitting_is_a_hard_gate():
    from lab import go_live
    g = go_live.gate4_overfitting(go_live._goal())
    # current IS/OOS gap (1.69) exceeds the 1.5 hard limit -> must FAIL
    assert g["status"] in ("FAIL", "MISSING")


# --- sign-off hash binding ---------------------------------------------------
def test_signoff_requires_pack_hash(tmp_path, monkeypatch):
    from lab import go_live
    # a sign-off without reviewed_pack_sha must not pass, even if everything else set
    cfg = go_live.CONFIG / "go_live_signoff.yaml"
    original = cfg.read_text() if cfg.exists() else None
    try:
        cfg.write_text("approved: true\napproved_by: X\ndate: 2026-01-01\n")
        g = go_live.gate7_signoff()
        assert g["status"] == "FAIL"  # missing paper record AND/OR pack hash
    finally:
        if original is not None:
            cfg.write_text(original)
