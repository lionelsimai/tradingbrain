"""FIX-13 (red-team §17): the AI tool layer must be unable to trade. The existing
permission test only scans agents/*.py (trivial dataclasses); it does NOT scan the
large LLM tool modules (scripts/agent/hermes_tools.py ~48KB, scripts/collective/).
This test scans those too: no import of a broker/order path, no write-method def.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["scripts/agent", "scripts/agents", "scripts/collective", "agents"]

FORBIDDEN_IMPORTS = [
    "execution.broker_base", "execution.order_manager", "execution.paper_adapter",
    "execution.alpaca_paper_adapter", "scripts.broker_alpaca", "scripts.paper_broker",
    "safety.kill_switch",
]
FORBIDDEN_DEFS = ["submit_order", "call_broker", "place_order", "cancel_order", "size_position"]


def _py_files():
    for d in SCAN_DIRS:
        p = ROOT / d
        if p.exists():
            yield from p.rglob("*.py")


def _is_forbidden_import(txt: str, imp: str) -> bool:
    pkg, name = imp.rsplit(".", 1)
    if re.search(rf"(^|\n)[ \t]*import[ \t]+{re.escape(imp)}\b", txt):
        return True
    # `from <pkg> import <name>` (possibly in a comma list)
    if re.search(rf"(^|\n)[ \t]*from[ \t]+{re.escape(pkg)}[ \t]+import[ \t]+[^\n]*\b{re.escape(name)}\b", txt):
        return True
    return False


def test_ai_tool_layer_has_no_broker_imports():
    offenders = []
    for f in _py_files():
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for imp in FORBIDDEN_IMPORTS:
            if _is_forbidden_import(txt, imp):
                offenders.append(f"{f.relative_to(ROOT)} imports {imp}")
    assert not offenders, "AI tool layer must not import broker/order path: " + "; ".join(offenders)


def test_ai_tool_layer_defines_no_write_methods():
    offenders = []
    for f in _py_files():
        txt = f.read_text(encoding="utf-8", errors="ignore")
        for d in FORBIDDEN_DEFS:
            # a real `def submit_order(...)` that ISN'T a guard that raises PermissionError
            for m in re.finditer(rf"(^|\n)[ \t]*def[ \t]+{re.escape(d)}\b", txt):
                body = txt[m.end():m.end() + 240]
                if "PermissionError" not in body and "raise" not in body:
                    offenders.append(f"{f.relative_to(ROOT)} defines {d}() that does not raise")
    assert not offenders, "AI tool layer write-method offenders: " + "; ".join(offenders)
