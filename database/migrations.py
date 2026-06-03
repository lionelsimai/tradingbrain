#!/usr/bin/env python3
"""Forward-only migration runner. Each migration has an id + an idempotent apply().
Applied ids are recorded in the migrations table so they run exactly once.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import schema


def _applied(con) -> set[str]:
    try:
        return {r[0] for r in con.execute("SELECT id FROM migrations").fetchall()}
    except Exception:
        return set()


# id -> (description, sql)
MIGRATIONS: list[tuple[str, str, str]] = [
    ("0001_exec_tables", "create exec/paper tables", schema.EXEC_SCHEMA),
    ("0002_equity_curve_index", "equity curve ordering",
     "CREATE INDEX IF NOT EXISTS idx_equity_ts ON paper_equity_curve(ts);"),
]


def run(path: Path | None = None) -> dict:
    schema.init(path)
    con = schema.connect(path)
    done = _applied(con)
    ran = []
    for mid, desc, sql in MIGRATIONS:
        if mid in done:
            continue
        try:
            con.execute(sql)
            con.execute("INSERT INTO migrations (id, description) VALUES (?, ?)", [mid, desc])
            ran.append(mid)
        except Exception as e:
            con.close()
            return {"ok": False, "ran": ran, "error": f"{mid}: {e}"}
    con.close()
    return {"ok": True, "ran": ran, "already": sorted(done)}


if __name__ == "__main__":
    import json
    print(json.dumps(run(), indent=2))
