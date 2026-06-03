#!/usr/bin/env python3
"""Bridge the tested recommendation engine to the app's database schema.

The v1 app stores picks in Supabase. Rather than have an LLM invent entry/stop/
target (a hallucination risk on the exact numbers that define risk), the app
ingests the REAL engine output: this converts reports/recommendations.json and
the paper ledger into rows that match app/supabase/schema.sql exactly.

It also folds in the validation verdicts (gauntlet + go-live) and the
survivorship/conviction-cap honesty signals so the front end can show them.

Output: reports/app-export.json with {run, recommendations[], paper_trades[],
replay_trades[], evidence_summary}.

CLI:
  python3 -m scripts.export_app          # write reports/app-export.json
  python3 -m scripts.export_app --print   # also print it
"""
from __future__ import annotations
import json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT

REPORTS = ROOT / "reports"
OUT = REPORTS / "app-export.json"


def _connect_knowledge_readonly():
    """Open the ledger DB without taking a writer lock.

    Export is a read-only bridge to the app, and validators may run at the same
    time as schema checks or paper loops. Asking DuckDB for a read-only handle
    keeps this path from blocking on unrelated writers.
    """
    import duckdb
    return duckdb.connect(str(ROOT / "data" / "knowledge.duckdb"), read_only=True)


def _load(name, default=None):
    try:
        return json.loads((REPORTS / name).read_text())
    except Exception:
        return default if default is not None else {}


def _ledger_trades(source_filter: tuple[str, ...] | None, limit: int = 200) -> list[dict]:
    """Recent ledger trades mapped to the app trade shape.

    Provenance is explicit. `paper_trades` must never contain replay rows, because
    the app treats them as the forward record. Replay rows are exposed separately
    as research-only evidence.
    """
    c = _connect_knowledge_readonly()
    where = ""
    params: list[object] = []
    if source_filter:
        where = "WHERE source IN (" + ",".join("?" for _ in source_filter) + ")"
        params.extend(source_filter)
    params.append(limit)
    try:
        rows = c.execute(
            f"""SELECT id, ticker, entry, stop, t1, status, emit_ts, exit_date,
                       realized_R, mfe_R, mae_R, exit_reason,
                       COALESCE(source, 'paper') AS source
                FROM signal_ledger {where} ORDER BY emit_ts DESC LIMIT ?""", params).fetchall()
    finally:
        c.close()
    status_map = {"won": "hit_target", "lost": "hit_stop", "open": "open"}
    out = []
    for r in rows:
        out.append({
            "source_signal_id": r[0], "ticker": r[1],
            "entry": r[2], "stop": r[3], "target": r[4],
            "status": status_map.get(r[5], r[5]),
            "opened_at": str(r[6]), "closed_at": str(r[7]) if r[7] else None,
            "result_r": r[8], "mfe_r": r[9], "mae_r": r[10], "exit_reason": r[11],
            "source": r[12],
        })
    return out


def _paper_trades(limit: int = 200) -> list[dict]:
    """Paper evidence only. Real-live evidence is never put in paper_trades."""
    return _ledger_trades(("paper",), limit=limit)


def _live_trades(limit: int = 200) -> list[dict]:
    """Real-capital evidence only."""
    return _ledger_trades(("live",), limit=limit)


def _replay_trades(limit: int = 200) -> list[dict]:
    """Replay evidence for research context only; never counted as paper."""
    return _ledger_trades(("replay",), limit=limit)


def _evidence_summary() -> dict:
    c = _connect_knowledge_readonly()
    try:
        rows = c.execute(
            """SELECT COALESCE(source, 'paper') AS source,
                      status,
                      COUNT(*) AS n
               FROM signal_ledger
               GROUP BY 1, 2"""
        ).fetchall()
    finally:
        c.close()
    summary = {
        "paper_open": 0,
        "paper_resolved": 0,
        "live_open": 0,
        "live_resolved": 0,
        "replay_open": 0,
        "replay_resolved": 0,
        "paper_trades_are_forward_only": True,
        "note": (
            "paper_trades contains only paper ledger rows. Live and replay rows "
            "are exposed separately so evidence sources cannot be conflated."
        ),
    }
    for source, status, n in rows:
        resolved = status in ("won", "lost", "hit_target", "hit_stop", "timeout")
        if source == "paper":
            summary["paper_resolved" if resolved else "paper_open"] += int(n)
        elif source == "live":
            summary["live_resolved" if resolved else "live_open"] += int(n)
        elif source == "replay":
            summary["replay_resolved" if resolved else "replay_open"] += int(n)
    summary["forward_open"] = summary["paper_open"] + summary["live_open"]
    summary["forward_resolved"] = summary["paper_resolved"] + summary["live_resolved"]
    return summary


def build_export() -> dict:
    rec = _load("recommendations.json", {})
    gl = _load("go-live.json", {})
    gaunt = _load("gauntlet.json", {})

    run_id = str(uuid.uuid4())
    run = {
        "id": run_id,
        "ran_at": rec.get("asof", datetime.now(timezone.utc).isoformat()),
        "market_read": rec.get("market_read", ""),
        "tickers_scanned": rec.get("survivorship", {}).get("universe_size"),
        "picks_generated": len(rec.get("picks", [])),
        "conviction_cap_active": rec.get("conviction_cap_active"),
        "live_trades_on_record": rec.get("live_trades_on_record"),
        "gauntlet_verdict": gaunt.get("verdict"),
        "go_live_verdict": gl.get("verdict"),
        "survivorship_warning": rec.get("survivorship", {}).get("warning"),
        "disclaimer": rec.get("disclaimer"),
    }

    recommendations = []
    for p in rec.get("picks", []):
        ez = p.get("entry_zone", {}) or {}
        recommendations.append({
            "id": str(uuid.uuid4()), "run_id": run_id,
            "ticker": p.get("ticker"), "asset_class": p.get("asset_class", "equity"),
            "direction": p.get("direction"),
            "conviction_score": p.get("conviction_score"),
            "conviction_band": p.get("conviction_band"),
            "time_horizon": p.get("time_horizon"),
            "entry_low": ez.get("low"), "entry_high": ez.get("high"),
            "stop_loss": p.get("stop_loss"),
            "targets": p.get("targets"),
            "reward_to_risk": p.get("reward_to_risk"),
            "position_size": p.get("position_size"),
            "thesis": p.get("thesis"),
            "pillar_reads": p.get("pillar_reads"),
            "key_risks": p.get("key_risks"),
            "invalidation": p.get("invalidation"),
            "confidence_caveats": p.get("confidence_caveats"),
            "data_freshness": p.get("data_freshness"),
        })

    return {"run": run, "recommendations": recommendations,
            "paper_trades": _paper_trades(),
            "live_trades": _live_trades(),
            "replay_trades": _replay_trades(),
            "evidence_summary": _evidence_summary(),
            "watch_list": rec.get("watch_list", []),
            "no_qualifying_setups": rec.get("no_qualifying_setups", False)}


def validate(export: dict) -> list[str]:
    """Confirm the export matches the schema's expectations before the app ingests it."""
    problems = []
    REC_KEYS = {"id", "run_id", "ticker", "conviction_score", "conviction_band",
                "entry_low", "entry_high", "stop_loss", "targets", "reward_to_risk"}
    for r in export["recommendations"]:
        missing = REC_KEYS - set(r)
        if missing:
            problems.append(f"recommendation {r.get('ticker')} missing {missing}")
        # safety invariant: no 'strong' while the cap is active
        if export["run"]["conviction_cap_active"] and r.get("conviction_band") == "strong":
            problems.append(f"{r.get('ticker')} is 'strong' while conviction cap active")
        # levels must be real numbers, never null (the whole point of the bridge)
        if r.get("stop_loss") is None or r.get("entry_low") is None:
            problems.append(f"{r.get('ticker')} has null price level — engine must compute it")
    for t in export["paper_trades"]:
        if t.get("source") == "replay":
            problems.append(f"paper_trade {t.get('ticker')} is replay-sourced")
        if t["status"] not in ("open", "hit_target", "hit_stop", "timeout"):
            problems.append(f"paper_trade {t.get('ticker')} bad status {t['status']}")
    return problems


def main():
    export = build_export()
    problems = validate(export)
    OUT.write_text(json.dumps(export, indent=2, default=str))
    print(f"app export -> {OUT.name}: {len(export['recommendations'])} recs, "
          f"{len(export['paper_trades'])} paper trades, "
          f"gauntlet={export['run']['gauntlet_verdict']}, go_live={export['run']['go_live_verdict']}")
    if problems:
        print("VALIDATION PROBLEMS:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("export validates against the app schema.")
    if "--print" in sys.argv:
        print(json.dumps(export, indent=2, default=str))


if __name__ == "__main__":
    main()
