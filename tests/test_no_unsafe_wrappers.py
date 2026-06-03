#!/usr/bin/env python3
"""Fail if any shell wrapper or routine can place/cancel/close orders directly."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_active_alpaca_wrapper_has_no_write_verbs():
    w = (ROOT / "scripts" / "wrappers" / "alpaca.sh").read_text()
    assert "-X POST" not in w, "active wrapper can POST orders"
    assert "-X DELETE" not in w, "active wrapper can DELETE orders/positions"


def test_no_shell_wrapper_posts_orders():
    for sh in (ROOT / "scripts").rglob("*.sh"):
        t = sh.read_text()
        assert not re.search(r"-X\s+POST.*/v2/orders", t), f"{sh} posts orders"
        assert not re.search(r"-X\s+DELETE.*/v2/(orders|positions)", t), f"{sh} cancels/closes"


def test_routines_do_not_call_wrapper_for_writes():
    rdir = ROOT / "routines"
    if not rdir.exists():
        return
    for md in rdir.rglob("*.md"):
        t = md.read_text().lower()
        for verb in ("alpaca.sh order", "alpaca.sh cancel", "alpaca.sh close"):
            assert verb not in t, f"{md} instructs direct order action: {verb}"


def test_unsafe_wrapper_is_quarantined_and_inert():
    q = ROOT / "deprecated" / "unsafe_wrappers" / "alpaca.sh"
    assert q.exists() and "exit 3" in q.read_text()
