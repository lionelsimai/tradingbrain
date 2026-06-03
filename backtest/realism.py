#!/usr/bin/env python3
"""Backtest realism manifest + stress battery (Section 27). Declares — honestly —
exactly what the backtest does and does NOT model, plus a stress summary so a
single good SPY number can never be mistaken for an edge.

Writes reports/backtest-realism.json.
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import REPORTS_DIR
from backtest import trade_sim
from scorecards import effective_sample


def realism_manifest() -> dict:
    """Honest declaration of modelling fidelity. False = NOT modelled."""
    return {
        "survivorship_bias_free": False,          # universe = today's survivors
        "point_in_time_universe": False,          # no historical membership
        "total_return_adjusted": False,
        "split_adjusted": True,
        "dividend_adjusted": False,
        "delisted_included": False,
        "fee_model": "per-trade bps (commission)",
        "slippage_model": "fixed bps per side",
        "spread_model": "fixed bps",
        "liquidity_model": "none (assumes fill at modelled price)",
        "trade_delay_model": "signal-bar close entry (next-open variant tested)",
        "same_bar_policy": "stop checked before target (conservative)",
        "stop_execution_policy": "structural stop, scale-out 50% at T1",
        "target_execution_policy": "T1 then breakeven runner to T2",
        "gap_policy": "intrabar low<=stop fills at stop (no worse-fill on gaps)",
        "benchmark_SPY": True,
        "benchmark_QQQ": True,
        "benchmark_SMH": False,
        "benchmark_equal_weight_universe": True,
        "benchmark_buy_hold_universe": True,
        "opportunity_cost": "reported vs equal-weight basket (lab/benchmark)",
        "trust_level": "INDICATIVE — survivorship + non-point-in-time; not proof of live edge",
    }


def cost_stress(R: np.ndarray) -> dict:
    """Expectancy under escalating cost assumptions (R is gross per-trade)."""
    out = {}
    for label, bps in [("base_9bps", 9), ("2x_18bps", 18), ("4x_36bps", 36)]:
        cR = trade_sim.costs_to_R(commission_bps=bps / 3, slippage_bps=bps / 3, spread_bps=bps / 3)
        net = R - cR
        out[label] = round(float(net.mean()), 4)
    return out


def stress_battery(R: np.ndarray) -> dict:
    R = np.asarray(R, dtype=float)
    if len(R) < 20:
        return {"note": "insufficient trades"}
    srt = np.sort(R)[::-1]
    return {
        "cost_stress_expectancy_R": cost_stress(R),
        "remove_top_5_trades_expectancy_R": round(float(srt[5:].mean()), 4),
        "remove_top_1pct_expectancy_R": round(float(srt[max(1, len(R)//100):].mean()), 4),
        "worst_decile_mean_R": round(float(srt[-len(R)//10:].mean()), 4),
        "effective_sample": effective_sample.analyze(R, avg_hold_bars=8, step_bars=3),
    }


def build(R: np.ndarray | None = None) -> dict:
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "realism": realism_manifest(),
    }
    if R is not None:
        manifest["stress"] = stress_battery(np.asarray(R, dtype=float))
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "backtest-realism.json").write_text(json.dumps(manifest, indent=2))
    return manifest


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    m = build(rng.normal(0.1, 1.0, 800))
    print(json.dumps({"realism_flags": m["realism"], "stress": m["stress"]["cost_stress_expectancy_R"]},
                     indent=2))
