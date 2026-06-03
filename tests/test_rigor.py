#!/usr/bin/env python3
"""Rigor test suite — the automated guarantees that keep this a 10/10 instrument.

Run with: python3 -m pytest tests/test_rigor.py -q
"""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT))

from lab import stats as st
from lab import validate as val


# ----------------------------------------------------------- correctness proofs
def test_no_lookahead():
    """Corrupting all data after T must not change the decision/plan at T."""
    r = val.check_no_lookahead(n_points=12)
    assert r["failures"] == [], f"look-ahead leak: {r['failures']}"
    assert r["checked"] >= 5


def test_live_equals_backtest():
    """The vectorized backtest detector must equal the live detector exactly."""
    r = val.check_live_eq_backtest()
    assert r["mismatches"] == 0, f"{r['mismatches']} live/backtest mismatches"


def test_determinism_seeded():
    """Seeded resampling is byte-reproducible."""
    st.seed_everything(1)
    a = st.stationary_bootstrap_ci(np.arange(200) % 7 - 3.0)
    st.seed_everything(1)
    b = st.stationary_bootstrap_ci(np.arange(200) % 7 - 3.0)
    assert a == b


# ------------------------------------------------------------- statistics sanity
def test_effective_sample_size_iid():
    """For iid data, effective N ~ N."""
    rng = np.random.default_rng(0)
    x = rng.normal(0, 1, 1000)
    assert 850 <= st.effective_sample_size(x) <= 1000


def test_effective_sample_size_autocorrelated():
    """Positively autocorrelated data has FEWER effective samples."""
    rng = np.random.default_rng(0)
    e = rng.normal(0, 1, 2000)
    x = np.zeros(2000)
    for i in range(1, 2000):
        x[i] = 0.6 * x[i - 1] + e[i]
    assert st.effective_sample_size(x) < 1000  # << 2000


def test_pbo_noise_is_uninformative():
    """Pure-noise strategies => PBO ~ 0.5 on average (selection no better than
    random). A single small draw is noisy, so average over realizations."""
    rng = np.random.default_rng(0)
    pbos = []
    for _ in range(12):
        M = rng.normal(0, 1, (64, 6))
        r = st.pbo_cscv(M, n_splits=16)
        if r["pbo"] is not None:
            pbos.append(r["pbo"])
    assert pbos and 0.35 <= float(np.mean(pbos)) <= 0.65


def test_pbo_real_edge_is_low():
    """One strategy with a persistent real edge => low PBO."""
    rng = np.random.default_rng(0)
    M = rng.normal(0, 1, (32, 6))
    M[:, 0] += 1.5  # strategy 0 genuinely better every slice
    r = st.pbo_cscv(M, n_splits=16)
    assert r["pbo"] is not None and r["pbo"] < 0.25


def test_deflated_sharpe_penalizes_trials():
    """More trials => lower DSR for the same observed Sharpe."""
    rng = np.random.default_rng(0)
    R = rng.normal(0.05, 1.0, 1500)
    dsr_few, _ = st.deflated_sharpe_ratio(R, sr_trials_std=0.03, n_trials=2)
    dsr_many, _ = st.deflated_sharpe_ratio(R, sr_trials_std=0.03, n_trials=200)
    assert dsr_many < dsr_few


def test_probabilistic_sharpe_bounds():
    rng = np.random.default_rng(0)
    assert 0.0 <= st.probabilistic_sharpe_ratio(rng.normal(0.1, 1, 500)) <= 1.0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
