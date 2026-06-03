#!/usr/bin/env python3
"""Scorecard source-separation policy (Section 15). The rules that keep replay
and paper evidence from ever driving the live gate."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import risk_policy

SOURCES = ("live", "paper", "replay", "backtest")


def min_trades(source: str) -> int:
    sp = risk_policy.load().get("scorecard_policy", {})
    return {
        "live": int(sp.get("live_min_trades", 30)),
        "paper": int(sp.get("paper_min_trades", 50)),
        "replay": int(sp.get("replay_min_effective_trades", 100)),
        "backtest": 100,
    }.get(source, 100)


def may_drive_live_gate(source: str) -> bool:
    """Only live evidence may drive the live gate."""
    return source == "live"


def may_drive_calibration(source: str, target_mode: str) -> bool:
    """Calibration for a given mode must use the matching source (or replay only
    to SUPPRESS). Combined view never drives calibration."""
    if source == "combined":
        return False
    if target_mode == "live":
        return source == "live"
    if target_mode == "paper":
        return source in ("paper", "replay")   # replay suppress-only
    return True


def evidence_sufficient(source: str, n: int) -> bool:
    return n >= min_trades(source)


if __name__ == "__main__":
    print("replay drives live gate:", may_drive_live_gate("replay"))
    print("live drives live gate:", may_drive_live_gate("live"))
    print("combined drives calibration:", may_drive_calibration("combined", "paper"))
    print("live evidence sufficient (5):", evidence_sufficient("live", 5))
