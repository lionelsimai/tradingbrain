#!/usr/bin/env python3
"""Smoke + invariant tests for TradingBrain core."""
import json, sys, subprocess
from pathlib import Path
import numpy as np

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "scripts"))

from brain.hmm_regime import causal_states, stability_filter, LABELS, ALLOC


# --- HMM ---
def test_causal_states_uses_only_past():
    """The filtered posterior at time t should NOT change when we add future data."""
    from hmmlearn.hmm import GaussianHMM
    rng = np.random.RandomState(0)
    X = rng.randn(40, 2)
    m = GaussianHMM(n_components=3, n_iter=10, random_state=0).fit(X)
    _, post_full = causal_states(m, X)
    _, post_truncated = causal_states(m, X[:25])
    np.testing.assert_allclose(post_full[:25], post_truncated, atol=1e-8)


def test_stability_filter_requires_consecutive():
    states = np.array([0, 1, 1, 1, 2, 2, 0, 0, 0, 0])
    acted, status, vol = stability_filter(states, min_consecutive=3, lookback=10, max_flicker=4)
    assert acted == 0  # last regime to persist 3+ consecutive bars


def test_stability_filter_flicker_warning():
    states = np.tile([0, 1], 10)
    acted, status, vol = stability_filter(states, min_consecutive=3, lookback=10, max_flicker=4)
    assert vol is True
    assert status == "VOLATILE"


def test_alloc_table_complete():
    for label in LABELS:
        assert label in ALLOC, f"missing target_exposure for {label}"
        assert 0 <= ALLOC[label] <= 1


# --- Circuit breakers ---
def test_circuit_breaker_no_data_is_clear():
    out = subprocess.check_output([sys.executable, "-m", "scripts.brain.circuit_breakers"], cwd=str(ROOT)).decode()
    assert "All circuits clear" in out or "clear" in out.lower()


# --- Allocation ---
def test_allocation_scalar_in_range():
    subprocess.check_output([sys.executable, "-m", "scripts.brain.allocation"], cwd=str(ROOT)).decode()
    data = json.loads((ROOT / "reports" / "allocation.json").read_text())
    s = data["final_sizing_scalar"]
    assert 0 <= s <= 1.0


# --- WQ alphas ---
def test_wq_composite_writes_signals():
    out = subprocess.check_output([sys.executable, "-m", "scripts.alphas.compute"], cwd=str(ROOT)).decode()
    assert "wq_composite" in out or "composite" in out.lower()


# --- Walk-forward ---
def test_walkforward_runs_and_reports_alpha():
    out = subprocess.check_output([sys.executable, "-m", "backtest.walk_forward"], cwd=str(ROOT)).decode()
    assert "Median OOS Sharpe" in out
