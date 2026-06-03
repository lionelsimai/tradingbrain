"""Realized-outcome evidence loader — the brain's track record, honestly sourced.

Reads the source-separated scorecards the system already produces:
  * reports/scorecard-live.json   — REAL broker/paper fills (the only evidence
                                     allowed to lift the moderate conviction cap).
  * reports/scorecard-replay.json — historical replay on the curated universe
                                     (survivorship-biased -> indicative ceiling).

Exposes per-setup evidence with the live/replay source clearly tagged. Mirrors
the SETUP_ALIAS proxying in scripts/calibration.py so a live setup without its
own sample inherits its proxy's stats.
"""
from __future__ import annotations

import json
from pathlib import Path

# A live setup without its own backtest sample inherits a proxy's calibration.
SETUP_ALIAS = {"MOMO_CONT": "TREND_LEADER"}

# Minimum live sample before live evidence is trusted enough to lift the cap.
MIN_LIVE_N = 20
# Minimum replay sample before replay evidence is used as a (capped) prior.
MIN_REPLAY_N = 10


def _resolve(setup: str) -> str:
    return SETUP_ALIAS.get(setup, setup)


def _read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def _norm_setup_row(row: dict, source: str) -> dict:
    n = int(row.get("n", 0) or 0)
    wr = row.get("win_rate")
    # scorecards store win_rate as a percent (e.g. 70.0); normalise to 0..1.
    p_win = (float(wr) / 100.0) if wr is not None else None
    return {
        "n": n,
        "p_win": p_win,
        "expectancy_R": float(row.get("expectancy_R", 0.0) or 0.0),
        "avg_win_R": float(row.get("avg_win_R", 0.0) or 0.0),
        "avg_loss_R": float(row.get("avg_loss_R", 0.0) or 0.0),
        "profit_factor": float(row.get("profit_factor", 0.0) or 0.0),
        "source": source,
    }


class Outcomes:
    """Loaded, source-separated outcome evidence."""

    def __init__(self, reports_dir: Path):
        reports_dir = Path(reports_dir)
        live = _read(reports_dir / "scorecard-live.json")
        replay = _read(reports_dir / "scorecard-replay.json")
        self.live_by_setup = (live.get("by_setup") or {})
        self.replay_by_setup = (replay.get("by_setup") or {})
        self.live_overall = (live.get("overall") or live.get("overall_live") or {})
        self.replay_overall = (replay.get("overall") or replay.get("overall_replay") or {})
        self.live_n = int(self.live_overall.get("n", 0) or 0)
        self.replay_n = int(self.replay_overall.get("n", 0) or 0)

    @property
    def base_rate(self) -> float:
        """Universe-wide win rate to shrink small samples toward (0..1)."""
        for overall in (self.live_overall, self.replay_overall):
            wr = overall.get("win_rate")
            if wr is not None:
                return max(0.05, min(0.95, float(wr) / 100.0))
        return 0.5

    def setup_evidence(self, setup: str) -> dict:
        """Best available evidence for a setup, live preferred over replay.

        Returns {n, p_win, expectancy_R, avg_win_R, avg_loss_R, source}.
        source is 'live' | 'replay' | 'none'. Only a 'live' source with
        n >= MIN_LIVE_N is allowed to lift the moderate cap downstream.
        """
        key = _resolve(setup)
        live = self.live_by_setup.get(key)
        if live and int(live.get("n", 0) or 0) >= MIN_LIVE_N:
            return _norm_setup_row(live, "live")
        replay = self.replay_by_setup.get(key)
        if replay and int(replay.get("n", 0) or 0) >= MIN_REPLAY_N:
            return _norm_setup_row(replay, "replay")
        # thin live sample is still returned (tagged) but won't lift the cap
        if live and int(live.get("n", 0) or 0) > 0:
            return _norm_setup_row(live, "live")
        return {"n": 0, "p_win": None, "expectancy_R": 0.0, "avg_win_R": 0.0,
                "avg_loss_R": 0.0, "profit_factor": 0.0, "source": "none"}


def load(reports_dir: Path) -> Outcomes:
    return Outcomes(reports_dir)
