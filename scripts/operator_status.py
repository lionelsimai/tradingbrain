#!/usr/bin/env python3
"""Operator status snapshot (mode, kill switch, health). Section 35."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import config_guard, kill_switch
from monitoring import health

if __name__ == "__main__":
    print(json.dumps({"mode": config_guard.mode(),
                      "kill_switch": kill_switch.status(),
                      "health": health.check()}, indent=2, default=str))
