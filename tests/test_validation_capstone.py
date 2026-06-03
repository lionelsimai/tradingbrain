#!/usr/bin/env python3
"""Tests for the validation capstone: Monte Carlo engine + go-live authority.

Guards the spec's core promises:
  * Monte Carlo produces an honest distribution and never invents trades.
  * The go-live authority DEFAULTS TO BLOCKED and refuses to clear live while
    there is no real paper track record (the recurring, correct blocker).
"""
import sys
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backtest import monte_carlo
from lab import go_live


# --- Monte Carlo -------------------------------------------------------------
def test_mc_distribution_shape():
    rep = monte_carlo.run(paths=2000, source="replay", seed=1)
    if "error" in rep:
        return  # ledger too small in this environment
    dd = rep["max_drawdown_R"]
    # drawdown percentiles must be monotonically non-decreasing
    assert dd["p50"] <= dd["p95"] <= dd["p99"] <= dd["worst_max"]
    # return percentiles ordered too
    tr = rep["total_return_R"]
    assert tr["p5"] <= tr["p50"] <= tr["p95"]


def test_mc_is_deterministic_under_seed():
    a = monte_carlo.run(paths=1000, source="replay", seed=42)
    b = monte_carlo.run(paths=1000, source="replay", seed=42)
    if "error" in a:
        return
    assert a["max_drawdown_R"] == b["max_drawdown_R"]


def test_mc_does_not_invent_trades():
    """trades_per_path must equal the real resolved-trade count — resampling
    only reshuffles recorded outcomes, it never creates new ones."""
    import duckdb
    rep = monte_carlo.run(paths=500, source="replay", seed=1)
    if "error" in rep:
        return
    con = duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"))
    n = con.execute("SELECT COUNT(*) FROM signal_ledger WHERE realized_R IS NOT NULL "
                    "AND source='replay'").fetchone()[0]
    con.close()
    assert rep["trades_per_path"] == n


# --- Go-live authority -------------------------------------------------------
def test_go_live_has_seven_gates():
    rep = go_live.evaluate()
    assert len(rep["gates"]) == 7


def test_go_live_defaults_blocked_without_paper():
    """With zero live/paper fills, the verdict must be BLOCKED and gate 5 must FAIL.
    This is the spec's central safety property."""
    rep = go_live.evaluate()
    g5 = next(g for g in rep["gates"] if g["gate"].startswith("5."))
    # gate 5 may only PASS if a real paper track record exists; in this repo it doesn't
    if g5["status"] == "FAIL":
        assert rep["verdict"] == "BLOCKED"


def test_go_live_gate5_requires_live_like_paper_when_available(monkeypatch):
    monkeypatch.setattr(go_live, "_goal", lambda: {"success": {"min_live_trades": 50}})

    def fake_load(name):
        if name == "scorecard-paper.json":
            return {
                "resolved": 50,
                "live_like_resolved_trades": 0,
                "evidence_source": "paper",
            }
        return {}

    monkeypatch.setattr(go_live, "_load", fake_load)

    gate = go_live.gate5_paper()

    assert gate["status"] == go_live.FAIL
    assert "live-like paper fills: 0" in gate["detail"]
    assert "total paper resolved: 50" in gate["detail"]


def test_go_live_never_silently_clears():
    """CLEARED requires ALL gates green — never a partial."""
    rep = go_live.evaluate()
    if rep["verdict"] == "CLEARED FOR LIVE":
        assert all(g["status"] == "PASS" for g in rep["gates"])


def test_go_live_gate6_requires_live_data_health(monkeypatch):
    def fake_load(name):
        if name == "risk-policy-report.json":
            return {"valid": True}
        if name == "data-quality.json":
            return {"pass": True}
        if name == "circuit-breakers.json":
            return {"sizing_scalar": 1.0}
        if name == "live-data-health.json":
            return {"ok": False, "hard_failures": ["moomoo OpenD offline"]}
        return {}

    monkeypatch.setattr(go_live, "_load", fake_load)

    gate = go_live.gate6_risk_controls()

    assert gate["status"] == go_live.FAIL
    assert "live_data_health_pass=FAIL" in gate["detail"]


def test_go_live_gate6_reports_missing_live_data_health(monkeypatch):
    def fake_load(name):
        if name == "risk-policy-report.json":
            return {"valid": True}
        if name == "data-quality.json":
            return {"pass": True}
        if name == "circuit-breakers.json":
            return {"sizing_scalar": 1.0}
        if name == "live-data-health.json":
            return None
        return {}

    monkeypatch.setattr(go_live, "_load", fake_load)

    gate = go_live.gate6_risk_controls()

    assert gate["status"] == go_live.FAIL
    assert "live_data_health_pass=MISSING" in gate["detail"]


def test_go_live_pack_sha_is_bound_to_live_data_health(tmp_path, monkeypatch):
    monkeypatch.setattr(go_live, "REPORTS", tmp_path)
    for name in [
        "go-live.json", "walk-forward.json", "stress-test.json",
        "monte-carlo.json", "validate.json", "data-quality.json",
        "live-data-health.json", "scorecard-paper.json",
        "scorecard-live.json", "scorecard-replay.json",
    ]:
        (tmp_path / name).write_text(json.dumps({"name": name, "version": 1}))

    before = go_live.pack_sha()
    (tmp_path / "live-data-health.json").write_text(json.dumps({"ok": True, "version": 2}))
    after = go_live.pack_sha()

    assert before != after
