#!/usr/bin/env python3
"""Scorecard row schema (Section 15). Every row declares its evidence_source."""
from __future__ import annotations

REQUIRED_FIELDS = [
    "setup", "strategy", "evidence_source", "source_file", "raw_n", "effective_n",
    "n_live", "n_paper", "n_replay", "n_backtest", "expectancy_R", "win_rate",
    "avg_win_R", "avg_loss_R", "profit_factor", "max_drawdown_R",
    "confidence_interval_low", "confidence_interval_high", "overlap_ratio",
    "regime", "benchmark", "generated_at", "code_version",
]


def validate_row(row: dict) -> tuple[bool, list[str]]:
    missing = [f for f in REQUIRED_FIELDS if f not in row]
    if row.get("evidence_source") not in ("live", "paper", "replay", "backtest"):
        missing.append("evidence_source(invalid)")
    return (not missing, missing)


if __name__ == "__main__":
    print(validate_row({"setup": "VCP"}))
