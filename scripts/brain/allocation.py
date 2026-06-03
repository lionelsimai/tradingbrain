#!/usr/bin/env python3
"""Allocation engine — gives the broker a sizing scalar.

Inputs:
  - HMM regime + target exposure (reports/hmm-regime.json)
  - Open paper positions (paper_positions where status=OPEN)
  - Total risk budget (default 5%)
  - Circuit-breaker state (reports/circuit-breakers.json, if present)

Output: scalar in [0, 1] applied to every new position size.
  1.0 = full sizing  ·  0.5 = half size  ·  0.0 = halt
"""
from __future__ import annotations
import json, sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from db import kb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
HMM = ROOT / "reports" / "hmm-regime.json"
CB = ROOT / "reports" / "circuit-breakers.json"
OUT = ROOT / "reports" / "allocation.json"


def main():
    con = kb()
    open_risk = con.execute(
        "SELECT COALESCE(SUM(risk_pct), 0) FROM paper_positions WHERE status = 'OPEN'"
    ).fetchone()[0]
    open_count = con.execute(
        "SELECT COUNT(*) FROM paper_positions WHERE status = 'OPEN'"
    ).fetchone()[0]

    regime = json.loads(HMM.read_text()) if HMM.exists() else {"target_exposure": 0.60, "regime": "Neutral"}
    cb = json.loads(CB.read_text()) if CB.exists() else {"sizing_scalar": 1.0, "trip_reasons": [], "drawdown_pct": 0.0}

    target = float(regime["target_exposure"])
    regime_scalar = target
    final_scalar = regime_scalar * float(cb["sizing_scalar"])
    mode = "HALT" if final_scalar == 0 else ("DEFENSIVE" if final_scalar < 0.3 else ("MODERATE" if final_scalar < 0.7 else "AGGRESSIVE"))

    out = {
        "asof": str(date.today()),
        "acted_label": regime.get("acted_label", regime.get("raw_label")),
        "raw_label": regime.get("raw_label"),
        "stability": regime.get("stability", "STABLE"),
        "volatile_warning": regime.get("volatile_warning", False),
        "target_exposure": target,
        "regime_scalar": regime_scalar,
        "circuit_scalar": float(cb["sizing_scalar"]),
        "final_sizing_scalar": round(final_scalar, 2),
        "mode": mode,
        "open_risk_pct": open_risk,
        "open_count": open_count,
        "circuit_trips": cb.get("trip_reasons", []),
    }
    OUT.write_text(json.dumps(out, indent=2))
    print(f"Allocation · {out['mode']}  scalar={final_scalar:.2f}")
    _label = regime.get("regime") or regime.get("acted_label") or regime.get("raw_label") or "Neutral"
    print(f"  regime={_label}  target_exp={target:.0%}  open_risk={open_risk:.2f}%  open={open_count}")
    print(f"  circuit: {cb['sizing_scalar']:.2f} ({cb.get('reason')})")


if __name__ == "__main__":
    main()
