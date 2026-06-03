#!/usr/bin/env python3
"""Master kill switch + granular pause state. File-backed (reports/safety_state.json)
so EVERY process — broker, loops, operator CLI — reads the same truth, and it
survives restarts.

States:
  halt_all       — engage() : no new orders at all (the big red button).
  paused_strategies / paused_symbols — selective pause.

Fail-closed reads: if the state file is unreadable, callers treat the system as
HALTED. Better to stop trading than to trade blind.

CLI:
  python3 -m safety.kill_switch status
  python3 -m safety.kill_switch engage "reason"
  python3 -m safety.kill_switch release
"""
from __future__ import annotations
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "reports" / "safety_state.json"

_DEFAULT = {
    "halt_all": False,
    "halt_reason": None,
    "paused_strategies": [],
    "paused_symbols": [],
    "updated_at": None,
}


def _read() -> dict:
    if not STATE.exists():
        return dict(_DEFAULT)
    try:
        d = json.loads(STATE.read_text())
        return {**_DEFAULT, **d}
    except Exception:
        # Unreadable state -> fail closed (treat as halted).
        return {**_DEFAULT, "halt_all": True, "halt_reason": "state file unreadable (fail-closed)"}


def _write(d: dict):
    d["updated_at"] = datetime.now(timezone.utc).isoformat()
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(d, indent=2))


def is_halted() -> bool:
    return bool(_read().get("halt_all"))


def engage(reason: str = "manual"):
    d = _read()
    d["halt_all"] = True
    d["halt_reason"] = reason
    _write(d)
    return d


def release():
    d = _read()
    d["halt_all"] = False
    d["halt_reason"] = None
    _write(d)
    return d


def pause_strategy(name: str):
    d = _read()
    if name not in d["paused_strategies"]:
        d["paused_strategies"].append(name)
    _write(d)
    return d


def resume_strategy(name: str):
    d = _read()
    d["paused_strategies"] = [s for s in d["paused_strategies"] if s != name]
    _write(d)
    return d


def pause_symbol(sym: str):
    d = _read()
    sym = sym.upper()
    if sym not in d["paused_symbols"]:
        d["paused_symbols"].append(sym)
    _write(d)
    return d


def resume_symbol(sym: str):
    d = _read()
    d["paused_symbols"] = [s for s in d["paused_symbols"] if s != sym.upper()]
    _write(d)
    return d


def blocked(symbol: str | None = None, strategy: str | None = None) -> str | None:
    """Return a reason string if trading is blocked for this symbol/strategy, else None."""
    d = _read()
    if d.get("halt_all"):
        return f"kill switch engaged: {d.get('halt_reason')}"
    if strategy and strategy in d.get("paused_strategies", []):
        return f"strategy paused: {strategy}"
    if symbol and symbol.upper() in d.get("paused_symbols", []):
        return f"symbol paused: {symbol.upper()}"
    return None


def status() -> dict:
    return _read()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "engage":
        reason = sys.argv[2] if len(sys.argv) > 2 else "manual"
        print(json.dumps(engage(reason), indent=2))
    elif cmd == "release":
        print(json.dumps(release(), indent=2))
    else:
        print(json.dumps(status(), indent=2))


if __name__ == "__main__":
    main()
