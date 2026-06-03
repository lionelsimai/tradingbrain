#!/usr/bin/env python3
"""System health check — one call the operator/CI can run to see if the system is
in a safe, consistent state."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def check() -> dict:
    out = {"ok": True, "components": {}}
    def rec(name, ok, detail=""):
        out["components"][name] = {"ok": ok, "detail": detail}
        if not ok: out["ok"] = False
    # config + policy
    try:
        from safety import risk_policy
        v = risk_policy.report(); rec("risk_policy", v["valid"], str(v.get("conflicts")))
    except Exception as e:
        rec("risk_policy", False, str(e))
    # kill switch readable
    try:
        from safety import kill_switch
        kill_switch.status(); rec("kill_switch", True, "halted" if kill_switch.is_halted() else "clear")
    except Exception as e:
        rec("kill_switch", False, str(e))
    # db schema
    try:
        from database import schema
        v = schema.validate(); rec("db_schema", v["ok"], str(v.get("missing")))
    except Exception as e:
        rec("db_schema", False, str(e))
    # config guard mode
    try:
        from safety import config_guard
        rec("mode", True, config_guard.mode())
    except Exception as e:
        rec("mode", False, str(e))
    # live market-data provider readiness
    try:
        from monitoring import live_data_health
        v = live_data_health.check()
        rec("live_data", v["ok"], "; ".join(v.get("hard_failures", [])) or v["status"])
    except Exception as e:
        rec("live_data", False, str(e))
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(check(), indent=2))
