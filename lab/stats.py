#!/usr/bin/env python3
"""Gold-standard significance tools for backtest evaluation.

Everything here is built to AVOID the two ways backtests lie:
  1. Overlapping/autocorrelated trades make the sample look bigger than it is
     -> effective_sample_size + stationary_bootstrap_ci.
  2. Trying many strategies guarantees a good-looking winner by luck
     -> probabilistic_sharpe_ratio, deflated_sharpe_ratio, and pbo_cscv
        (Probability of Backtest Overfitting, Bailey & Lopez de Prado 2015).

References:
  - Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio".
  - Bailey, Borwein, Lopez de Prado, Zhu (2015), "The Probability of Backtest
    Overfitting" (CSCV).
  - Politis & Romano (1994), "The Stationary Bootstrap".

Pure NumPy/SciPy-free (uses a local normal CDF/PPF) so it runs anywhere.
"""
from __future__ import annotations
import math
import os
from itertools import combinations
import numpy as np

EULER_MASCHERONI = 0.5772156649015329

# Seedable RNG for all resampling here — set TB_SEED for reproducible runs.
_RNG = np.random.default_rng(int(os.environ.get("TB_SEED", "1")))


def seed_everything(seed: int | None = None) -> int:
    """Reseed this module's RNG and numpy's legacy global RNG. Returns the seed."""
    global _RNG
    s = int(os.environ.get("TB_SEED", "1")) if seed is None else int(seed)
    _RNG = np.random.default_rng(s)
    np.random.seed(s)
    return s


# ---------------------------------------------------------------- normal dist
def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """Inverse normal CDF (Acklam's rational approximation; abs err < 1.15e-9)."""
    if p <= 0.0:
        return -math.inf
    if p >= 1.0:
        return math.inf
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


# ------------------------------------------------------- effective sample size
def autocorr(x: np.ndarray, lag: int) -> float:
    if lag >= len(x):
        return 0.0
    x = x - x.mean()
    denom = float(np.dot(x, x))
    if denom == 0:
        return 0.0
    return float(np.dot(x[:-lag], x[lag:]) / denom)


def effective_sample_size(R, max_lag: int = 50) -> float:
    """n_eff = n / (1 + 2*sum rho_k). Overlapping/serially-correlated trades
    shrink the *independent* information content. Returns <= n."""
    x = np.asarray(R, dtype=float)
    n = len(x)
    if n < 8:
        return float(n)
    s = 0.0
    for k in range(1, min(max_lag, n - 1) + 1):
        rho = autocorr(x, k)
        if rho <= 0 and k > 1:          # truncate at first non-positive (Geyer)
            break
        s += (1 - k / n) * rho
    n_eff = n / (1 + 2 * s)
    return float(max(1.0, min(n, n_eff)))


# ------------------------------------------------------ stationary bootstrap CI
def stationary_bootstrap_ci(R, alpha: float = 0.05, n_boot: int = 2000,
                            seed: int = 7, mean_block: float | None = None):
    """CI for mean(R) that RESPECTS serial dependence (Politis-Romano).
    Blocks of random geometric length preserve autocorrelation, so the interval
    doesn't pretend overlapping trades are independent."""
    x = np.asarray(R, dtype=float)
    n = len(x)
    if n < 10:
        return [None, None]
    if mean_block is None:
        mean_block = max(2.0, math.sqrt(n))
    p = 1.0 / mean_block
    rng = np.random.default_rng(seed)
    means = np.empty(n_boot)
    for b in range(n_boot):
        idx = np.empty(n, dtype=int)
        i = rng.integers(0, n)
        for t in range(n):
            idx[t] = i
            if rng.random() < p:
                i = rng.integers(0, n)
            else:
                i = (i + 1) % n
        means[b] = x[idx].mean()
    lo = float(np.percentile(means, 100 * alpha / 2))
    hi = float(np.percentile(means, 100 * (1 - alpha / 2)))
    return [round(lo, 4), round(hi, 4)]


# --------------------------------------------------- probabilistic / deflated SR
def _sharpe(R) -> float:
    x = np.asarray(R, dtype=float)
    sd = x.std(ddof=1)
    return float(x.mean() / sd) if sd > 0 else 0.0


def _skew_kurt(R):
    x = np.asarray(R, dtype=float)
    n = len(x)
    sd = x.std(ddof=0)
    if sd == 0 or n < 4:
        return 0.0, 3.0
    m3 = ((x - x.mean()) ** 3).mean() / sd ** 3
    m4 = ((x - x.mean()) ** 4).mean() / sd ** 4
    return float(m3), float(m4)


def probabilistic_sharpe_ratio(R, sr_benchmark: float = 0.0):
    """P(true SR > benchmark) given skew/kurtosis and sample size (per-trade SR)."""
    x = np.asarray(R, dtype=float)
    n = len(x)
    if n < 8:
        return None
    sr = _sharpe(x)
    skew, kurt = _skew_kurt(x)
    denom = math.sqrt(max(1e-12, 1 - skew * sr + (kurt - 1) / 4 * sr ** 2))
    z = (sr - sr_benchmark) * math.sqrt(n - 1) / denom
    return round(norm_cdf(z), 4)


def expected_max_sharpe(sr_trials_std: float, n_trials: int) -> float:
    """Expected maximum of n_trials i.i.d. Sharpes ~ N(0, sr_trials_std^2).
    This is the bar a winning backtest must clear to not be luck."""
    if n_trials < 2 or sr_trials_std <= 0:
        return 0.0
    g = EULER_MASCHERONI
    return sr_trials_std * ((1 - g) * norm_ppf(1 - 1.0 / n_trials) +
                            g * norm_ppf(1 - 1.0 / (n_trials * math.e)))


def deflated_sharpe_ratio(R, sr_trials_std: float, n_trials: int):
    """Deflated Sharpe Ratio (Bailey & Lopez de Prado 2014): the PSR evaluated
    against the *expected best* Sharpe from n_trials attempts. A DSR near 1 means
    the result is unlikely to be a multiple-testing artifact; near 0.5 or below
    means it's plausibly luck."""
    sr_star = expected_max_sharpe(sr_trials_std, n_trials)
    return probabilistic_sharpe_ratio(R, sr_benchmark=sr_star), round(sr_star, 4)


def min_track_record_length(R, sr_benchmark: float = 0.0, conf: float = 0.95):
    """Trades needed before SR is statistically > benchmark at `conf`."""
    x = np.asarray(R, dtype=float)
    if len(x) < 8:
        return None
    sr = _sharpe(x)
    if sr <= sr_benchmark:
        return None
    skew, kurt = _skew_kurt(x)
    z = norm_ppf(conf)
    mtrl = 1 + (1 - skew * sr + (kurt - 1) / 4 * sr ** 2) * (z / (sr - sr_benchmark)) ** 2
    return int(math.ceil(mtrl))


# ------------------------------------------- Probability of Backtest Overfitting
def pbo_cscv(perf_matrix, n_splits: int = 16):
    """Probability of Backtest Overfitting via Combinatorially-Symmetric
    Cross-Validation (Bailey et al. 2015).

    perf_matrix: shape (T, N) — T time-slices x N candidate strategies/configs,
                 each cell a performance score for that slice (e.g. total R).
    Returns PBO = fraction of IS-optimal selections that land below the OOS
    median — i.e. how often picking the in-sample winner backfires out-of-sample.
    Lower is better; > 0.5 means the selection process is worse than random.
    """
    M = np.asarray(perf_matrix, dtype=float)
    T, N = M.shape
    if N < 2 or T < n_splits or n_splits % 2 != 0:
        return {"pbo": None, "n_combos": 0, "note": "insufficient data for CSCV"}
    # split rows into n_splits contiguous blocks
    bounds = np.array_split(np.arange(T), n_splits)
    blocks = [b for b in bounds if len(b) > 0]
    S = len(blocks)
    if S % 2 != 0:
        blocks = blocks[:-1]
        S = len(blocks)
    half = S // 2
    logits = []
    for combo in combinations(range(S), half):
        is_idx = np.concatenate([blocks[i] for i in combo])
        oos_idx = np.concatenate([blocks[i] for i in range(S) if i not in combo])
        is_perf = M[is_idx].mean(axis=0)
        oos_perf = M[oos_idx].mean(axis=0)
        n_star = int(np.argmax(is_perf))              # IS-optimal strategy
        # relative rank of that strategy OOS (1 = worst .. N = best)
        order = oos_perf.argsort().argsort()          # 0..N-1
        rank = order[n_star] + 1
        omega = rank / (N + 1)
        omega = min(max(omega, 1e-6), 1 - 1e-6)
        logits.append(math.log(omega / (1 - omega)))
    logits = np.asarray(logits)
    pbo = float((logits <= 0).mean())                 # fraction that underperform median
    return {
        "pbo": round(pbo, 4),
        "n_combos": len(logits),
        "logit_mean": round(float(logits.mean()), 4),
        "interpretation": ("LOW overfit risk" if pbo < 0.25 else
                           "MODERATE overfit risk" if pbo < 0.5 else
                           "HIGH overfit risk (selection worse than random)"),
    }


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    # self-test: a genuine small edge
    R = rng.normal(0.05, 1.0, 1500)
    print("sharpe", round(_sharpe(R), 3))
    print("n_eff", round(effective_sample_size(R), 0), "of", len(R))
    print("boot CI", stationary_bootstrap_ci(R))
    print("PSR>0", probabilistic_sharpe_ratio(R))
    print("DSR (20 trials)", deflated_sharpe_ratio(R, sr_trials_std=0.03, n_trials=20))
    print("MinTRL", min_track_record_length(R))
    # PBO self-test: 5 noise strategies over 32 slices -> PBO should be ~0.5
    M = rng.normal(0, 1, (32, 5))
    print("PBO(noise)", pbo_cscv(M))
