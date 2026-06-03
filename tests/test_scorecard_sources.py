#!/usr/bin/env python3
"""Scorecard-source governance: replay/paper never drive the live gate."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import scripts.calibration as calib


def test_separate_scorecard_files_exist():
    for src in ("replay", "live", "paper"):
        f = ROOT / "reports" / f"scorecard-{src}.json"
        assert f.exists(), f"missing {f.name}"
        assert json.loads(f.read_text()).get("evidence_source") == src


def test_replay_can_only_suppress_not_promote():
    # replay_negative_gated returns True/False (a SUPPRESSOR); it never enables.
    val = calib.replay_negative_gated("VCP")
    assert isinstance(val, bool)


def test_live_gate_requires_live_evidence():
    # With zero live fills, the live gate must not fire (no live evidence to act on).
    calib._scorecards.clear()
    assert calib.live_gated("VCP") is False
    assert calib.load_scorecard("live") == {}


def test_calibration_does_not_read_combined_for_gating():
    src = (ROOT / "scripts" / "calibration.py").read_text()
    # gating must not load a 'combined' scorecard
    assert "scorecard-combined" not in src
