#!/usr/bin/env python3
"""Explicit order-lifecycle state machine. Invalid transitions raise — you can
never go proposed->submitted without approval, or rejected->filled.
"""
from __future__ import annotations

STATES = (
    "proposed", "rejected_pretrade", "approved", "pending_human_review",
    "submitted", "acknowledged", "partially_filled", "filled",
    "stop_pending", "stop_active", "target_pending", "target_active",
    "protective_order_failed", "cancelled", "rejected_by_broker",
    "closing", "closed", "reconciled", "incident",
)

# allowed transitions: state -> set(next states)
TRANSITIONS: dict[str, set[str]] = {
    "proposed": {"rejected_pretrade", "approved", "pending_human_review"},
    "pending_human_review": {"approved", "rejected_pretrade"},
    "approved": {"submitted", "rejected_pretrade"},
    "submitted": {"acknowledged", "rejected_by_broker"},
    "acknowledged": {"partially_filled", "filled", "cancelled", "rejected_by_broker"},
    "partially_filled": {"partially_filled", "filled", "cancelled"},
    "filled": {"stop_pending", "target_pending", "closing", "reconciled", "incident"},
    "stop_pending": {"stop_active", "protective_order_failed"},
    "stop_active": {"target_pending", "closing", "closed", "incident"},
    "target_pending": {"target_active", "protective_order_failed"},
    "target_active": {"closing", "closed", "incident"},
    "protective_order_failed": {"incident", "closing"},
    "closing": {"closed", "incident"},
    "closed": {"reconciled"},
    "reconciled": set(),
    "rejected_pretrade": set(),
    "rejected_by_broker": set(),
    "cancelled": {"reconciled"},
    "incident": {"closing", "reconciled"},
}

TERMINAL = {"reconciled", "rejected_pretrade", "rejected_by_broker"}


class InvalidTransition(RuntimeError):
    pass


def can(frm: str, to: str) -> bool:
    return to in TRANSITIONS.get(frm, set())


def transition(frm: str, to: str) -> str:
    if frm not in STATES or to not in STATES:
        raise InvalidTransition(f"unknown state {frm!r}->{to!r}")
    if not can(frm, to):
        raise InvalidTransition(f"illegal transition {frm} -> {to}")
    return to


def is_terminal(state: str) -> bool:
    return state in TERMINAL


if __name__ == "__main__":
    print("proposed->approved:", can("proposed", "approved"))
    print("proposed->submitted:", can("proposed", "submitted"))
    print("rejected_pretrade->filled:", can("rejected_pretrade", "filled"))
    try:
        transition("proposed", "filled")
    except InvalidTransition as e:
        print("blocked:", e)
