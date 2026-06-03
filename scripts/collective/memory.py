#!/usr/bin/env python3
"""Memory Librarian — the backbone of inspectable learning (DOCTRINE v3 Part III).

Four layers in knowledge.duckdb:
  episodes        — every research run / decision with full context
  lessons         — durable generalized lessons (semantic memory)
  strategy_library— each setup's status + evidence + red-team/risk verdicts
  failure_log     — every way a strategy broke (most valuable data)

Retrieval discipline (Part III §7): query BEFORE spending fresh compute, so the
org never re-derives what it knows or re-tests a dead idea.
"""
from __future__ import annotations
import duckdb, json
from pathlib import Path
from datetime import datetime, timezone

KB = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent) / "data" / "knowledge.duckdb"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodes (
    id BIGINT PRIMARY KEY, ts TIMESTAMP, cycle_id VARCHAR, agent VARCHAR, task VARCHAR,
    hypothesis VARCHAR, data_window VARCHAR, result VARCHAR, decision VARCHAR, rationale VARCHAR
);
CREATE TABLE IF NOT EXISTS lessons (
    id BIGINT PRIMARY KEY, ts TIMESTAMP, cycle_id VARCHAR, lesson VARCHAR, category VARCHAR,
    evidence VARCHAR, confidence DOUBLE, times_reinforced INTEGER
);
CREATE TABLE IF NOT EXISTS failure_log (
    id BIGINT PRIMARY KEY, ts TIMESTAMP, cycle_id VARCHAR, setup VARCHAR, failure_mode VARCHAR,
    context VARCHAR, lesson_id BIGINT, source VARCHAR
);
CREATE TABLE IF NOT EXISTS strategy_library (
    setup VARCHAR PRIMARY KEY, status VARCHAR, verdict VARCHAR, oos_expectancy_R DOUBLE,
    red_team_findings VARCHAR, risk_officer_verdict VARCHAR, updated_at TIMESTAMP, evidence VARCHAR
);
"""


def _con():
    con = duckdb.connect(str(KB))
    con.execute(_SCHEMA)
    return con


def _read_con():
    return duckdb.connect(str(KB), read_only=True)


def _next_id(con, table: str) -> int:
    r = con.execute(f"SELECT COALESCE(MAX(id),0)+1 FROM {table}").fetchone()
    return int(r[0])

def record_episode(cycle_id, agent, task, hypothesis="", data_window="",
                   result=None, decision="", rationale="") -> int:
    con = _con()
    eid = _next_id(con, "episodes")
    con.execute("INSERT INTO episodes VALUES (?,?,?,?,?,?,?,?,?,?)",
                [eid, datetime.now(timezone.utc), cycle_id, agent, task, hypothesis,
                 data_window, json.dumps(result or {}, default=str), decision, rationale])
    con.close()
    return eid

def add_lesson(cycle_id, lesson, category="general", evidence="", confidence=0.6) -> int:
    """Add or reinforce a lesson. If a near-identical lesson exists, bump its count."""
    con = _con()
    existing = con.execute("SELECT id, times_reinforced FROM lessons WHERE lesson = ?",
                           [lesson]).fetchone()
    if existing:
        con.execute("UPDATE lessons SET times_reinforced = times_reinforced + 1, "
                    "confidence = LEAST(0.99, confidence + 0.05), ts = ? WHERE id = ?",
                    [datetime.now(timezone.utc), existing[0]])
        lid = existing[0]
    else:
        lid = _next_id(con, "lessons")
        con.execute("INSERT INTO lessons VALUES (?,?,?,?,?,?,?,?)",
                    [lid, datetime.now(timezone.utc), cycle_id, lesson, category,
                     evidence, confidence, 1])
    con.close()
    return lid

def log_failure(cycle_id, setup, failure_mode, context="", lesson_id=None, source="simulation") -> int:
    con = _con()
    fid = _next_id(con, "failure_log")
    con.execute("INSERT INTO failure_log VALUES (?,?,?,?,?,?,?,?)",
                [fid, datetime.now(timezone.utc), cycle_id, setup, failure_mode,
                 context, lesson_id, source])
    con.close()
    return fid

def upsert_strategy(setup, status, verdict, oos_expectancy_R=None,
                    red_team_findings="", risk_officer_verdict="", evidence=None):
    con = _con()
    con.execute("DELETE FROM strategy_library WHERE setup = ?", [setup])
    con.execute("INSERT INTO strategy_library VALUES (?,?,?,?,?,?,?,?)",
                [setup, status, verdict, oos_expectancy_R, red_team_findings,
                 risk_officer_verdict, datetime.now(timezone.utc),
                 json.dumps(evidence or {}, default=str)])
    con.close()

def retrieve(setup=None, category=None, limit=20) -> dict:
    """Retrieval discipline: pull prior lessons/failures/status before acting."""
    con = _read_con()
    out = {}
    if setup:
        row = con.execute("SELECT status, verdict, oos_expectancy_R, red_team_findings, "
                          "risk_officer_verdict FROM strategy_library WHERE setup = ?",
                          [setup]).fetchone()
        out["strategy_status"] = (dict(zip(
            ["status","verdict","oos_expectancy_R","red_team","risk_officer"], row))
            if row else None)
        out["failures"] = [dict(zip(["setup","failure_mode","context","source"], r))
            for r in con.execute("SELECT setup, failure_mode, context, source FROM "
            "failure_log WHERE setup = ? ORDER BY ts DESC LIMIT ?", [setup, limit]).fetchall()]
    q = "SELECT lesson, category, confidence, times_reinforced FROM lessons"
    params = []
    if category:
        q += " WHERE category = ?"; params.append(category)
    q += " ORDER BY times_reinforced DESC, confidence DESC LIMIT ?"; params.append(limit)
    out["lessons"] = [dict(zip(["lesson","category","confidence","reinforced"], r))
                      for r in con.execute(q, params).fetchall()]
    con.close()
    return out

def _experience(con, setup: str, regime: str | None = None) -> list[dict]:
    """The resolved-trade track record for a setup, grouped by source so replay
    and live are NEVER conflated. Every number carries its sample size n and a
    source label — this is the honesty contract for recalled facts. When a regime
    is given, the track record is restricted to that regime (now meaningful, since
    real point-in-time regime labels are written)."""
    where = "WHERE setup = ? AND realized_R IS NOT NULL"
    params = [setup]
    if regime:
        where += " AND regime = ?"
        params.append(regime)
    rows = con.execute(
        f"""SELECT source,
                  COUNT(*)                                            AS n,
                  ROUND(AVG(realized_R), 3)                           AS avg_R,
                  ROUND(100.0*AVG(CASE WHEN realized_R>0 THEN 1 ELSE 0 END),1) AS win_rate,
                  ROUND(AVG(mfe_R), 2)                                AS avg_mfe,
                  ROUND(AVG(mae_R), 2)                                AS avg_mae,
                  ROUND(AVG(hold_days), 1)                            AS avg_hold_days
           FROM signal_ledger
           {where}
           GROUP BY source ORDER BY n DESC""", params).fetchall()
    out = []
    for r in rows:
        src = r[0] or "unknown"
        label = "replay (INDICATIVE — survivorship-biased, not live)" \
            if src == "replay" else ("live" if src == "live" else src)
        out.append({"source": src, "source_label": label, "n": int(r[1]),
                    "avg_R": r[2], "win_rate": r[3], "avg_mfe": r[4],
                    "avg_mae": r[5], "avg_hold_days": r[6]})
    return out


def _experience_by_regime(con, setup: str) -> list[dict]:
    """How the setup performs across regimes — exposes 'great in bull, lethal in
    crash' instead of hiding it in a blended average."""
    rows = con.execute(
        """SELECT regime, COUNT(*) n, ROUND(AVG(realized_R),3) avg_R,
                  ROUND(100.0*AVG(CASE WHEN realized_R>0 THEN 1 ELSE 0 END),1) win_rate
           FROM signal_ledger
           WHERE setup = ? AND realized_R IS NOT NULL AND regime IS NOT NULL
           GROUP BY regime ORDER BY n DESC""", [setup]).fetchall()
    return [{"regime": r[0], "n": int(r[1]), "avg_R": r[2], "win_rate": r[3]}
            for r in rows]


def _exit_mix(con, setup: str, limit: int = 5) -> list[dict]:
    rows = con.execute(
        """SELECT exit_reason, COUNT(*) n FROM signal_ledger
           WHERE setup = ? AND exit_reason IS NOT NULL
           GROUP BY exit_reason ORDER BY n DESC LIMIT ?""", [setup, limit]).fetchall()
    return [{"exit_reason": r[0], "n": int(r[1])} for r in rows]


def _example_ids(con, setup: str, limit: int = 5) -> list[dict]:
    """Real signal ids so recalled experience can be audited — never fabricated."""
    rows = con.execute(
        """SELECT id, ticker, emit_date, realized_R, exit_reason FROM signal_ledger
           WHERE setup = ? AND realized_R IS NOT NULL
           ORDER BY emit_ts DESC LIMIT ?""", [setup, limit]).fetchall()
    return [{"signal_id": r[0], "ticker": r[1], "date": str(r[2]),
             "realized_R": r[3], "exit_reason": r[4]} for r in rows]


def recall(setup: str, regime: str | None = None, k: int = 5) -> dict:
    """Experience-grounded recall (the upgrade over retrieve()).

    Surfaces, for a setup: its resolved-trade TRACK RECORD (labeled replay vs
    live, with sample sizes), a per-regime breakdown, how it typically exits,
    real example signal ids, plus setup-scoped lessons and failures. Built so a
    decision can be informed by what actually happened — honestly, and without
    fabricating anything.

    When `regime` is given, the headline track record is restricted to that
    regime (now meaningful — real point-in-time regime labels are written).
    Lessons are decayed by age so stale, dead-regime lessons stop dominating.
    """
    con = _read_con()
    out: dict = {"setup": setup, "regime": regime}

    out["experience"] = _experience(con, setup, regime)
    out["experience_all_regimes"] = _experience(con, setup, None) if regime else None
    out["experience_by_regime"] = _experience_by_regime(con, setup)
    out["exit_mix"] = _exit_mix(con, setup, k)
    out["examples"] = _example_ids(con, setup, k)
    out["experience_note"] = (
        "Track record is REPLAY unless labeled live; replay is survivorship-biased "
        "and INDICATIVE only. Counts (n) are real and auditable via examples.")

    # strategy status, now carrying its evidence sample size + source label
    row = con.execute(
        "SELECT status, verdict, oos_expectancy_R FROM strategy_library WHERE setup = ?",
        [setup]).fetchone()
    if row:
        live_n = con.execute(
            "SELECT COUNT(*) FROM signal_ledger WHERE setup = ? AND realized_R IS NOT NULL "
            "AND source = 'live'", [setup]).fetchone()[0]
        out["strategy_status"] = {
            "status": row[0], "verdict": row[1], "oos_expectancy_R": row[2],
            "n": int(live_n), "source": "live" if live_n else "replay/backtest"}
    else:
        out["strategy_status"] = None

    # failures, scoped to this setup (most valuable data)
    out["failures"] = [dict(zip(["setup", "failure_mode", "context", "source"], r))
                       for r in con.execute(
        "SELECT setup, failure_mode, context, source FROM failure_log "
        "WHERE setup = ? ORDER BY ts DESC LIMIT ?", [setup, k]).fetchall()]

    # lessons SCOPED to this setup first (the precision fix), DECAYED by age so
    # stale lessons from dead regimes stop dominating. effective weight =
    # times_reinforced * confidence * 0.5^(age_days / 180)  (6-month half-life).
    raw = con.execute(
        "SELECT lesson, category, confidence, times_reinforced, ts FROM lessons "
        "WHERE LOWER(lesson) LIKE ?", [f"%{setup.lower()}%"]).fetchall()
    from datetime import datetime as _dt, timezone as _tz
    now = _dt.now(_tz.utc)
    scored = []
    for lesson, cat, conf, reinf, ts in raw:
        age_days = 0
        if isinstance(ts, _dt):
            t = ts if ts.tzinfo else ts.replace(tzinfo=_tz.utc)
            age_days = max(0, (now - t).days)
        decay = 0.5 ** (age_days / 180.0)
        weight = (reinf or 1) * (conf or 0.5) * decay
        scored.append((weight, age_days, {
            "lesson": lesson, "category": cat, "confidence": conf,
            "reinforced": reinf, "age_days": age_days,
            "decay_weight": round(weight, 3)}))
    scored.sort(key=lambda x: x[0], reverse=True)
    out["lessons"] = [s[2] for s in scored[:k]]
    out["lessons_scoped_to_setup"] = True
    out["lessons_decayed"] = True
    con.close()
    return out


def stats() -> dict:
    con = _read_con()
    s = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
         for t in ["episodes","lessons","strategy_library","failure_log"]}
    con.close()
    return s

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats(), indent=2))
    elif len(sys.argv) > 2 and sys.argv[1] == "recall":
        print(json.dumps(recall(setup=sys.argv[2]), indent=2, default=str))
    elif len(sys.argv) > 2 and sys.argv[1] == "retrieve":
        print(json.dumps(retrieve(setup=sys.argv[2]), indent=2, default=str))
    else:
        print(json.dumps(retrieve(), indent=2, default=str))
