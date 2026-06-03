#!/usr/bin/env python3
"""Trading mode + config validation. The system is PAPER by default and LIVE
*fails closed*: live trading is refused unless an explicit env flag is set AND
every required safeguard is present AND the kill switch is clear.

Modes (env TB_MODE): backtest | paper (default) | live
  - backtest : no broker, no orders. Research only.
  - paper    : simulated/sandbox broker only. Safe default for the agent.
  - live     : real broker. Requires TB_ALLOW_LIVE=1 + all safeguards + clean kill switch.

CLI: python3 -m safety.config_guard   (prints the resolved, masked safety status)
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "config" / "session.yaml"
SOURCES = ROOT / "config" / "sources.yaml"

VALID_MODES = ("backtest", "paper", "live")

# Required config keys for ANY trading (paper or live).
REQUIRED_SESSION_KEYS = [
    "account_equity_usd", "risk_per_trade_pct", "max_portfolio_heat_pct",
    "max_concurrent_positions", "max_position_pct", "min_reward_to_risk",
]
REQUIRED_RISK_RULES = [
    "max_position_pct", "max_sector_pct", "max_drawdown_halt_pct", "min_confidence",
]
# Extra requirements that must ALL hold before live is permitted.
LIVE_REQUIRED_ENV = ["TB_ALLOW_LIVE"]  # must == "1"


def mode() -> str:
    m = os.environ.get("TB_MODE", "paper").strip().lower()
    return m if m in VALID_MODES else "paper"


def _load(p: Path) -> dict:
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}


def mask(secret: str | None) -> str:
    """Mask a secret for safe logging: keep first 2 + last 2 chars."""
    if not secret:
        return "<unset>"
    s = str(secret)
    if len(s) <= 6:
        return "****"
    return f"{s[:2]}{'*' * (len(s) - 4)}{s[-2:]}"


def validate_config() -> list[str]:
    """Return a list of problems. Empty list == valid."""
    problems = []
    session = _load(SESSION)
    sources = _load(SOURCES)
    if not session:
        problems.append("config/session.yaml missing or unreadable")
    if not sources:
        problems.append("config/sources.yaml missing or unreadable")
    for k in REQUIRED_SESSION_KEYS:
        if k not in session:
            problems.append(f"session.yaml missing required key: {k}")
    rr = (sources or {}).get("risk_rules", {})
    for k in REQUIRED_RISK_RULES:
        if k not in rr:
            problems.append(f"sources.yaml risk_rules missing required key: {k}")
    # sanity bounds
    rpt = session.get("risk_per_trade_pct")
    if isinstance(rpt, (int, float)) and rpt > 2.0:
        problems.append(f"risk_per_trade_pct={rpt} exceeds the 2.0% hard ceiling")
    mpp = session.get("max_position_pct")
    if isinstance(mpp, (int, float)) and mpp > 35.0:
        problems.append(f"max_position_pct={mpp} is dangerously high (>35%)")
    return problems


def broker_keys_present() -> bool:
    return bool(os.environ.get("APCA_API_KEY_ID") and os.environ.get("APCA_API_SECRET_KEY"))


def safe_to_trade(target_mode: str | None = None) -> tuple[bool, list[str]]:
    """The single gate the execution layer asks before doing ANYTHING.
    Returns (ok, reasons_if_not). Fails closed."""
    m = (target_mode or mode())
    reasons = []

    problems = validate_config()
    reasons += problems

    # Kill switch is checked here so even a misconfigured caller can't bypass it.
    try:
        from safety import kill_switch
        if kill_switch.is_halted():
            state = kill_switch.status()
            halt_reason = state.get("halt_reason") or state.get("reason") or "unknown"
            reasons.append(f"kill switch ENGAGED: {halt_reason}")
    except Exception as e:  # pragma: no cover - defensive
        reasons.append(f"kill switch unreadable (fail closed): {e}")

    if m == "backtest":
        # backtest never trades; 'safe to trade' is false by definition.
        reasons.append("mode=backtest: no live/paper orders permitted")
        return (False, reasons)

    if m == "live":
        if os.environ.get("TB_ALLOW_LIVE") != "1":
            reasons.append("live mode requires TB_ALLOW_LIVE=1 (fail-closed)")
        if not broker_keys_present():
            reasons.append("live mode requires broker API keys in env")
        # Live demands the strictest config: a defined drawdown halt + confidence floor.
        rr = _load(SOURCES).get("risk_rules", {})
        if not rr.get("max_drawdown_halt_pct"):
            reasons.append("live mode requires risk_rules.max_drawdown_halt_pct")

    # paper mode: only config + kill switch must pass.
    return (len(reasons) == 0, reasons)


def status() -> dict:
    m = mode()
    ok, reasons = safe_to_trade(m)
    return {
        "mode": m,
        "default_mode": "paper",
        "safe_to_trade": ok,
        "blocking_reasons": reasons,
        "broker_keys": "present" if broker_keys_present() else "absent",
        "allow_live_flag": os.environ.get("TB_ALLOW_LIVE", "0"),
        "broker_key_id_masked": mask(os.environ.get("APCA_API_KEY_ID")),
    }


def main():
    import json
    st = status()
    print(json.dumps(st, indent=2))
    # Non-zero exit if someone asked for live but it's not safe — useful in CI/startup.
    if st["mode"] == "live" and not st["safe_to_trade"]:
        sys.exit(2)


if __name__ == "__main__":
    main()
