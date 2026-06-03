#!/usr/bin/env python3
"""Central incident recording + gating — one source of truth for "is something
wrong enough that we must stop?".

An incident is an append-only, auditable record. Severity ordering:

    info < warning < blocking < incident < critical

Gating policy (fail-closed):
  * blocking | incident | critical  -> block new entries.
  * incident | critical             -> also require human review.
  * critical                        -> also engage the kill switch.

Nothing here can enable trading or weaken a gate; it can only raise the bar.
Persistence is an append-only JSONL plus an open-incident snapshot, so the audit
trail survives restarts and a crash mid-write never loses prior incidents.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

SEVERITIES = ("info", "warning", "blocking", "incident", "critical")
_RANK = {s: i for i, s in enumerate(SEVERITIES)}
CATEGORIES = ("data", "execution", "broker", "reconciliation", "risk",
              "approval", "ai", "system")

BLOCK_NEW_ENTRIES = {"blocking", "incident", "critical"}
REQUIRE_HUMAN_REVIEW = {"incident", "critical"}
ENGAGE_KILL_SWITCH = {"critical"}

_RUNBOOK = {
    "data": "Run data-quality scan; block until critical sources are fresh. See RUNBOOK_LIVE_READINESS.md#data-outage.",
    "execution": "Freeze new entries; reconcile broker vs internal; confirm every open position has a stop. See RUNBOOK#filled-position-without-stop.",
    "broker": "Treat broker state as unknown -> fail closed; reconcile before any new order. See RUNBOOK#broker-disconnected.",
    "reconciliation": "Block new entries; resolve the mismatch; escalate ghost/missing positions. See RUNBOOK#ghost-position.",
    "risk": "Halt new entries; verify loss/drawdown limits; confirm kill switch state. See RUNBOOK#drawdown-breach.",
    "approval": "Live remains blocked; re-run go-live authority; require named human + matching pack hash. See RUNBOOK#approval-hash-mismatch.",
    "ai": "Treat AI output as proposal only; re-validate schema; lower confidence in final report. See RUNBOOK#ai-hallucination.",
    "system": "Capture logs; verify report/journal writes; escalate. See RUNBOOK#test-suite-failure.",
}


def severity_at_least(sev: str, floor: str) -> bool:
    return _RANK.get(sev, 0) >= _RANK.get(floor, 0)


@dataclass
class Incident:
    incident_id: str
    created_at: str
    severity: str
    category: str
    description: str
    symbol: Optional[str] = None
    strategy: Optional[str] = None
    evidence: dict = field(default_factory=dict)
    blocks_new_entries: bool = False
    requires_human_review: bool = False
    engages_kill_switch: bool = False
    resolved: bool = False
    resolved_at: Optional[str] = None
    resolved_by: Optional[str] = None
    runbook_step: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentLog:
    """Append-only incident log scoped to a directory (so tests stay isolated)."""

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = Path(base_dir or (ROOT / "reports" / "incidents"))
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.base_dir / "incidents.jsonl"
        self.snapshot = self.base_dir / "open_incidents.json"

    # ---- recording ----
    def record(self, severity: str, category: str, description: str, *,
               symbol: Optional[str] = None, strategy: Optional[str] = None,
               evidence: Optional[dict] = None,
               engage_kill_switch: bool = True) -> Incident:
        if severity not in SEVERITIES:
            raise ValueError(f"unknown severity {severity!r}; expected {SEVERITIES}")
        if category not in CATEGORIES:
            raise ValueError(f"unknown category {category!r}; expected {CATEGORIES}")
        created = _now()
        seed = f"{created}|{category}|{symbol}|{strategy}|{description}"
        iid = "INC-" + hashlib.sha256(seed.encode()).hexdigest()[:12]
        inc = Incident(
            incident_id=iid, created_at=created, severity=severity, category=category,
            description=description, symbol=symbol, strategy=strategy,
            evidence=evidence or {},
            blocks_new_entries=severity in BLOCK_NEW_ENTRIES,
            requires_human_review=severity in REQUIRE_HUMAN_REVIEW,
            engages_kill_switch=severity in ENGAGE_KILL_SWITCH,
            runbook_step=_RUNBOOK.get(category, "Escalate to a human operator."),
        )
        with self.jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(inc.to_dict()) + "\n")
        self._refresh_snapshot()
        # critical incidents fail the whole system closed by engaging the kill switch
        if inc.engages_kill_switch and engage_kill_switch:
            try:
                from safety import kill_switch
                kill_switch.engage(f"incident {iid}: {description[:80]}")
            except Exception:
                pass  # never let kill-switch wiring failure swallow the incident
        return inc

    # ---- reads ----
    def all_incidents(self) -> list[dict]:
        if not self.jsonl.exists():
            return []
        out = []
        for line in self.jsonl.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        return out

    def open_incidents(self) -> list[dict]:
        # last-write-wins by incident_id, then keep only unresolved
        latest: dict[str, dict] = {}
        for inc in self.all_incidents():
            latest[inc["incident_id"]] = inc
        return [i for i in latest.values() if not i.get("resolved")]

    def blocks_new_entries(self) -> bool:
        return any(i.get("severity") in BLOCK_NEW_ENTRIES for i in self.open_incidents())

    def requires_human_review(self) -> bool:
        return any(i.get("severity") in REQUIRE_HUMAN_REVIEW for i in self.open_incidents())

    def has_critical(self) -> bool:
        return any(i.get("severity") == "critical" for i in self.open_incidents())

    def resolve(self, incident_id: str, by: str) -> bool:
        found = next((i for i in self.all_incidents() if i["incident_id"] == incident_id), None)
        if not found:
            return False
        found = dict(found)
        found.update(resolved=True, resolved_at=_now(), resolved_by=by)
        with self.jsonl.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(found) + "\n")
        self._refresh_snapshot()
        return True

    def summary(self) -> dict:
        openi = self.open_incidents()
        by_sev = {s: sum(1 for i in openi if i.get("severity") == s) for s in SEVERITIES}
        return {
            "open": len(openi),
            "by_severity": by_sev,
            "blocks_new_entries": self.blocks_new_entries(),
            "requires_human_review": self.requires_human_review(),
            "has_critical": self.has_critical(),
            "incident_ids": [i["incident_id"] for i in openi],
        }

    def _refresh_snapshot(self) -> None:
        self.snapshot.write_text(json.dumps(
            {"asof": _now(), "open_incidents": self.open_incidents(),
             "summary_blocks_new_entries": self.blocks_new_entries()}, indent=2))


# ---- module-level default log (production reports/incidents) ----
_default: Optional[IncidentLog] = None


def default_log() -> IncidentLog:
    global _default
    if _default is None:
        env = os.environ.get("TB_INCIDENTS_DIR")
        _default = IncidentLog(Path(env) if env else None)
    return _default


def record(severity: str, category: str, description: str, **kw) -> Incident:
    return default_log().record(severity, category, description, **kw)


def blocks_new_entries() -> bool:
    return default_log().blocks_new_entries()


def open_incidents() -> list[dict]:
    return default_log().open_incidents()


def create_incident(
    *,
    severity: str,
    category: str,
    description: str,
    symbol: str | None = None,
    strategy: str | None = None,
    evidence: dict | None = None,
    runbook_step: str = "",
) -> dict:
    """Backward-compatible incident creator used by execution chaos modules.

    The underlying append-only IncidentLog is the source of truth. This wrapper
    preserves the original dict-returning API so older safety tests and broker
    probes keep working while newer code can use IncidentLog directly.
    """
    inc = default_log().record(
        severity,
        category,
        description,
        symbol=symbol,
        strategy=strategy,
        evidence=evidence,
    )
    rec = inc.to_dict()
    if runbook_step:
        rec["runbook_step"] = runbook_step
    return rec


def list_incidents(include_resolved: bool = False) -> list[dict]:
    rows = default_log().all_incidents() if include_resolved else default_log().open_incidents()
    return rows


def main() -> int:
    print(json.dumps(default_log().summary(), indent=2))
    return 0


def resolve_incident(incident_id: str, note: str = "") -> dict | None:
    ok = default_log().resolve(incident_id, by=note or "operator")
    if not ok:
        return None
    return next((i for i in default_log().all_incidents() if i.get("incident_id") == incident_id), None)


def clear_all() -> None:
    log = default_log()
    log.base_dir.mkdir(parents=True, exist_ok=True)
    log.jsonl.write_text("")
    log.snapshot.write_text(json.dumps(
        {"asof": _now(), "open_incidents": [], "summary_blocks_new_entries": False}, indent=2
    ))


if __name__ == "__main__":
    raise SystemExit(main())
