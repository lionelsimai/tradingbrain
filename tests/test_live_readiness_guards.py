#!/usr/bin/env python3
"""Guards: dashboard never overclaims; hardening loop never weakens; the
forbidden-config scan catches live-enablement."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_never_advertises_live_while_blocked():
    from monitoring import live_readiness_dashboard as dash
    d = dash.build()
    assert d["live_blocked"] is True
    assert d["truthfulness"]["advertises_live_ready"] is False
    assert d["verdict"] != "LIVE_REVIEW_CANDIDATE"
    # paper evidence shown must be forward-paper only (never replay)
    assert d["paper_evidence"]["resolved_forward_paper_obs"] == 0


def test_hardening_loop_keeps_live_blocked_and_never_aborts_clean():
    from loops import harden_live_readiness as hl
    rep = hl.harden(max_iters=1)
    assert rep["aborted"] is None
    assert rep["final_stress_verdict"] == "LIVE_BLOCKED"
    assert rep["trace"][0]["invariant_live_blocked"] is True
    assert rep["trace"][0]["invariant_forbidden_scan_pass"] is True
    assert rep["forbidden_patches_guarded"]  # the guard list is non-empty


def test_forbidden_scan_passes_on_clean_tree():
    r = subprocess.run(["bash", str(ROOT / "scripts" / "ci_forbidden_live_weakening.sh")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_forbidden_scan_catches_live_enablement():
    probe = ROOT / "config" / "_pytest_forbidden_probe.yaml"
    probe.write_text("live_trading_enabled: true\n")
    try:
        r = subprocess.run(["bash", str(ROOT / "scripts" / "ci_forbidden_live_weakening.sh")],
                           capture_output=True, text=True)
        assert r.returncode == 1
        assert "live_trading_enabled" in r.stdout
    finally:
        probe.unlink(missing_ok=True)
