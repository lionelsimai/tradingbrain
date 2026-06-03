#!/usr/bin/env python3
"""Column contracts — the columns code relies on, asserted against the live DB so
schema drift fails loudly instead of at 3am during execution.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import schema

# table -> required columns (a subset; drift in these breaks loops).
CONTRACTS = {
    "paper_account": ["snapshot_date", "equity", "n_open", "total_risk", "closed",
                       "realized_R", "unrealized_R"],
    "paper_positions": ["position_id", "ticker", "entry", "stop", "status"],
    "paper_orders": ["client_order_id", "ticker", "side", "qty", "status"],
    "paper_fills": ["fill_id", "client_order_id", "qty", "price"],
}


def check(path: Path | None = None) -> dict:
    con = schema.connect(path)
    problems = []
    for tbl, cols in CONTRACTS.items():
        try:
            have = {r[1] for r in con.execute(f"PRAGMA table_info('{tbl}')").fetchall()}
        except Exception:
            problems.append(f"{tbl}: missing table")
            continue
        for c in cols:
            if c not in have:
                problems.append(f"{tbl}.{c}: missing column")
    con.close()
    return {"ok": not problems, "problems": problems}


if __name__ == "__main__":
    import json
    schema.init()
    print(json.dumps(check(), indent=2))
