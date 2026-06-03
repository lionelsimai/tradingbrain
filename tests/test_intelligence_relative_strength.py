#!/usr/bin/env python3
"""Tests for sector/peer relative strength (stock-specific edge isolation)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.intelligence import relative_strength as rs


SECTOR_MAP = {"NVDA": "semis", "AMD": "semis", "TSM": "semis", "MU": "semis",
              "MSFT": "software", "GOOG": "software", "CRM": "software"}


def test_sector_map_from_universe():
    m = rs.sector_map_from_universe({"universe": {"semis": ["NVDA", "amd"], "ai": ["PLTR"]}})
    assert m["NVDA"] == "semis" and m["AMD"] == "semis" and m["PLTR"] == "ai"


def test_outperformer_scores_positive():
    returns = {"NVDA": 0.20, "AMD": 0.05, "TSM": 0.04, "MU": 0.03}
    prs = rs.peer_relative_strength(returns, "NVDA", SECTOR_MAP)
    assert prs is not None
    assert prs["rs_vs_peers"] > 0
    assert prs["sector_rank"] == 1.0  # best in cohort
    assert rs.conviction_points(prs) > 0


def test_laggard_scores_negative():
    returns = {"NVDA": -0.05, "AMD": 0.10, "TSM": 0.12, "MU": 0.08}
    prs = rs.peer_relative_strength(returns, "NVDA", SECTOR_MAP)
    assert prs["rs_vs_peers"] < 0
    assert rs.conviction_points(prs) < 0


def test_points_are_bounded():
    returns = {"NVDA": 5.0, "AMD": 0.0, "TSM": 0.0, "MU": 0.0}  # absurd outperformance
    prs = rs.peer_relative_strength(returns, "NVDA", SECTOR_MAP)
    assert abs(rs.conviction_points(prs)) <= rs.MAX_POINTS


def test_insufficient_peers_returns_none():
    returns = {"NVDA": 0.2, "AMD": 0.1}  # only 1 peer (< min_peers=3)
    assert rs.peer_relative_strength(returns, "NVDA", SECTOR_MAP) is None
    # and a missing read is a clean no-op
    assert rs.conviction_points(None) == 0.0


def test_unknown_ticker_returns_none():
    assert rs.peer_relative_strength({"XYZ": 0.1}, "XYZ", SECTOR_MAP) is None
