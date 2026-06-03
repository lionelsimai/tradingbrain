import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agents import permissions
from agents.schemas import ReportingAgent
import pytest

def test_no_agent_can_submit():
    for a in permissions.AGENT_PERMISSIONS:
        assert not permissions.can(a,"submit_order")
        assert not permissions.can(a,"call_broker")

def test_agent_blocked_at_runtime():
    with pytest.raises(PermissionError):
        ReportingAgent().submit_order()

def test_agent_source_no_broker_import():
    agents_dir = Path(__file__).resolve().parents[1] / "agents"
    for f in agents_dir.glob("*.py"):
        src = f.read_text()
        for bad in permissions.FORBIDDEN_IMPORTS:
            assert f"import {bad}" not in src, f"{f.name} imports {bad}"

def test_invalid_output_rejected():
    ok,_=permissions.validate_output("signal_agent",{"type":"x","qty":5})
    assert not ok


def _imports_forbidden(src: str, mod: str) -> bool:
    """True iff `src` actually IMPORTS `mod` (any form), ignoring comments/strings
    (anchored to import/from statements, so a docstring mention doesn't trip it)."""
    parent, _, leaf = mod.rpartition(".")
    pats = [rf"(?m)^\s*import\s+{re.escape(mod)}\b",
            rf"(?m)^\s*from\s+{re.escape(mod)}\b"]
    if parent:
        pats.append(rf"(?m)^\s*from\s+{re.escape(parent)}\s+import\s+[^\n#]*\b{re.escape(leaf)}\b")
    return any(re.search(p, src) for p in pats)


def test_llm_tool_modules_are_read_only():
    """FIX-13 (P1-9): the REAL agent tool layer — not just the agents/ dataclasses
    but scripts/agent (the 48KB LLM tool module), scripts/agents and
    scripts/collective — must never import a broker/order/kill-switch module."""
    root = Path(__file__).resolve().parents[1]
    scanned = 0
    for d in ("agents", "scripts/agent", "scripts/agents", "scripts/collective"):
        base = root / d
        if not base.exists():
            continue
        for f in base.rglob("*.py"):
            scanned += 1
            src = f.read_text(encoding="utf-8", errors="ignore")
            for bad in permissions.FORBIDDEN_IMPORTS:
                assert not _imports_forbidden(src, bad), \
                    f"{f.relative_to(root)} imports forbidden module {bad}"
    assert scanned >= 5, f"scan covered too few modules ({scanned}) — check paths"
