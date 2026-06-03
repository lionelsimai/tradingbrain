#!/usr/bin/env python3
"""Effective sample size + concentration warnings. Overlapping trades make a
backtest look more significant than it is; this quantifies the real evidence.
"""
from __future__ import annotations
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lab import stats as labstats


def effective_n(raw_n: int, avg_hold_bars: float, step_bars: float) -> float:
    """Section 16 formula: raw_n / max(1, avg_hold / step)."""
    return raw_n / max(1.0, avg_hold_bars / max(step_bars, 1e-9))


def analyze(returns_R, symbols=None, regimes=None, avg_hold_bars=8.0,
            step_bars=3.0) -> dict:
    R = np.asarray(list(returns_R), dtype=float)
    raw = len(R)
    eff_formula = effective_n(raw, avg_hold_bars, step_bars)
    eff_autocorr = labstats.effective_sample_size(R) if raw >= 10 else raw
    out = {
        "raw_n": raw,
        "effective_n_formula": round(eff_formula, 1),
        "effective_n_autocorr": round(float(eff_autocorr), 1),
        "overlap_ratio": round(raw / max(eff_formula, 1e-9), 2),
        "warnings": [],
    }
    if step_bars < avg_hold_bars:
        out["warnings"].append(f"step {step_bars}b < hold {avg_hold_bars}b: trades overlap")
    if eff_formula < raw * 0.5:
        out["warnings"].append("effective_n far below raw_n — significance overstated")
    # concentration
    if symbols is not None and raw:
        contrib: dict = {}
        for s, r in zip(symbols, R):
            contrib[s] = contrib.get(s, 0.0) + max(r, 0)
        tot = sum(contrib.values()) or 1.0
        top = max(contrib.values()) / tot * 100 if contrib else 0
        out["top_symbol_contribution_pct"] = round(top, 1)
        if top > 40:
            out["warnings"].append(f"one symbol drives {top:.0f}% of gains")
    if raw:
        srt = np.sort(R)[::-1]
        top1pct = srt[: max(1, raw // 100)].sum() / (R.sum() or 1.0) * 100
        out["top_trade_contribution_pct"] = round(float(top1pct), 1)
        if top1pct > 50:
            out["warnings"].append("top 1% of trades drive >50% of expectancy")
    return out


if __name__ == "__main__":
    import json
    rng = np.random.default_rng(1)
    print(json.dumps(analyze(rng.normal(0.1, 1, 500), avg_hold_bars=8, step_bars=3), indent=2))
