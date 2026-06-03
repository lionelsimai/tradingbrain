#!/usr/bin/env python3
"""Agent I/O schemas + base class. Every agent logs its model + prompt version and
produces a typed, validated output. No agent has order/broker permissions.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agents import permissions


@dataclass
class AgentOutput:
    agent: str
    type: str
    payload: dict
    model_version: str = "unset"
    prompt_version: str = "unset"
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class BaseAgent:
    name = "base"
    model_version = "unset"
    prompt_version = "unset"

    def emit(self, type_: str, payload: dict) -> AgentOutput:
        out = {"type": type_, **payload}
        ok, reason = permissions.validate_output(self.name, out)
        if not ok:
            raise PermissionError(f"{self.name} produced invalid output: {reason}")
        return AgentOutput(agent=self.name, type=type_, payload=payload,
                           model_version=self.model_version, prompt_version=self.prompt_version)

    # hard guards
    def submit_order(self, *a, **k):
        raise PermissionError("agents cannot submit orders")

    def call_broker(self, *a, **k):
        raise PermissionError("agents cannot call brokers")


class ResearchAgent(BaseAgent):
    name = "research_agent"

class SignalAgent(BaseAgent):
    name = "signal_agent"

class RiskExplainerAgent(BaseAgent):
    name = "risk_explainer_agent"

class PortfolioCommentaryAgent(BaseAgent):
    name = "portfolio_commentary_agent"

class ReportingAgent(BaseAgent):
    name = "reporting_agent"


if __name__ == "__main__":
    a = ReportingAgent()
    print(a.emit("report", {"body": "daily summary"}))
    try:
        a.submit_order()
    except PermissionError as e:
        print("blocked:", e)
