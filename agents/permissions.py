#!/usr/bin/env python3
"""AI agent permission model. Agents propose and explain; they NEVER touch the
broker, the order manager's submit, the risk policy, or the kill switch.

Permissions are declarative AND enforced: forbidden_imports lists modules an
agent module must not import, and a test (tests/test_agent_permissions.py) scans
agent source to prove it.
"""
from __future__ import annotations

# capability -> agents that have it
AGENT_PERMISSIONS = {
    "research_agent": {"read_public_data", "read_reports", "write_research_note"},
    "signal_agent": {"read_features", "emit_signal_candidate"},
    "risk_explainer_agent": {"read_risk_decision", "write_explanation"},
    "portfolio_commentary_agent": {"read_portfolio", "write_commentary"},
    "reporting_agent": {"read_reports", "write_report"},
}

# capabilities NO agent may ever have
FORBIDDEN_FOR_ALL = {
    "submit_order", "call_broker", "cancel_order", "close_position",
    "modify_risk_policy", "override_kill_switch", "write_credentials",
    "size_position",
}

# modules an agent module must not import (enforced by static test)
FORBIDDEN_IMPORTS = [
    "execution.broker_base", "execution.order_manager", "execution.paper_adapter",
    "scripts.broker_alpaca", "safety.kill_switch",
]


def can(agent: str, capability: str) -> bool:
    if capability in FORBIDDEN_FOR_ALL:
        return False
    return capability in AGENT_PERMISSIONS.get(agent, set())


def validate_output(agent: str, output: dict) -> tuple[bool, str]:
    """Reject malformed agent output. Agents return structured dicts only."""
    if not isinstance(output, dict):
        return False, "output must be a dict"
    if "type" not in output:
        return False, "output missing 'type'"
    # an agent can never emit an order/size instruction
    banned = {"order", "submit", "position_size", "qty", "broker"}
    if banned & set(output.keys()):
        return False, f"agent output contains forbidden keys {banned & set(output.keys())}"
    return True, "ok"


if __name__ == "__main__":
    print("research can submit_order:", can("research_agent", "submit_order"))
    print("signal can emit:", can("signal_agent", "emit_signal_candidate"))
    print("validate good:", validate_output("reporting_agent", {"type": "report", "body": "x"}))
    print("validate bad:", validate_output("signal_agent", {"type": "x", "qty": 10}))
