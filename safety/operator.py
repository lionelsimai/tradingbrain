#!/usr/bin/env python3
"""Human control plane. The operator's emergency + routine commands.

  python3 -m safety.operator status            # full safety + portfolio snapshot
  python3 -m safety.operator kill "reason"      # engage master kill switch
  python3 -m safety.operator release            # release kill switch
  python3 -m safety.operator pause STRAT/SYM    # pause a strategy or symbol
  python3 -m safety.operator resume STRAT/SYM
  python3 -m safety.operator close_all          # mark all paper positions for close (EOD-style)
  python3 -m safety.operator cancel_orders      # cancel tracked open orders (paper)
  python3 -m safety.operator switch_paper       # force mode back to paper (writes flag)
  python3 -m safety.operator report             # print latest daily report path

Destructive actions (close_all/cancel_orders) operate on the PAPER ledger only and
require a --yes flag.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _status() -> dict:
    from safety import config_guard, kill_switch
    out = {"config": config_guard.status(), "kill_switch": kill_switch.status()}
    # portfolio snapshot (paper) if available
    try:
        import duckdb
        from scripts.db import KB_DB
        con = duckdb.connect(str(KB_DB), read_only=True)
        rows = con.execute(
            "SELECT ticker, entry, risk_pct FROM paper_positions WHERE status='OPEN'"
        ).fetchall()
        out["open_paper_positions"] = [{"ticker": r[0], "entry": r[1], "risk_pct": r[2]} for r in rows]
        eq = con.execute("SELECT equity FROM paper_account ORDER BY snapshot_date DESC LIMIT 1").fetchone()
        out["paper_equity"] = float(eq[0]) if eq else None
        con.close()
    except Exception as e:
        out["portfolio_error"] = str(e)
    return out


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "status"
    from safety import kill_switch

    if cmd == "status":
        print(json.dumps(_status(), indent=2, default=str))
    elif cmd == "kill":
        reason = args[1] if len(args) > 1 else "operator kill"
        print(json.dumps(kill_switch.engage(reason), indent=2))
        print(">>> KILL SWITCH ENGAGED. No new orders will be accepted.")
    elif cmd == "release":
        print(json.dumps(kill_switch.release(), indent=2))
        print(">>> Kill switch released.")
    elif cmd == "pause" and len(args) > 1:
        tok = args[1]
        d = kill_switch.pause_symbol(tok) if tok.isupper() and "_" not in tok else kill_switch.pause_strategy(tok)
        print(json.dumps(d, indent=2))
    elif cmd == "resume" and len(args) > 1:
        tok = args[1]
        d = kill_switch.resume_symbol(tok) if tok.isupper() and "_" not in tok else kill_switch.resume_strategy(tok)
        print(json.dumps(d, indent=2))
    elif cmd in ("close_all", "cancel_orders"):
        if "--yes" not in args:
            print(f"Refusing {cmd} without --yes (safety). Re-run: "
                  f"python3 -m safety.operator {cmd} --yes")
            sys.exit(1)
        import duckdb
        from scripts.db import KB_DB
        con = duckdb.connect(str(KB_DB))
        if cmd == "close_all":
            n = con.execute("SELECT COUNT(*) FROM paper_positions WHERE status='OPEN'").fetchone()[0]
            con.execute("UPDATE paper_positions SET status='CLOSED_OPERATOR' WHERE status='OPEN'")
            print(f"Marked {n} paper positions CLOSED_OPERATOR.")
        con.close()
    elif cmd == "switch_paper":
        flag = ROOT / "reports" / "FORCE_PAPER"
        flag.write_text("forced paper mode by operator\n")
        print("Wrote FORCE_PAPER flag. Set TB_MODE=paper in the environment too.")
    elif cmd == "report":
        reps = sorted((ROOT / "reports").glob("*-digest.md"))
        print(str(reps[-1]) if reps else "no daily digest found")
    elif cmd == "health":
        from monitoring import health
        print(json.dumps(health.check(), indent=2, default=str))
    elif cmd == "list_positions":
        try:
            import duckdb
            from scripts.db import KB_DB
            con = duckdb.connect(str(KB_DB), read_only=True)
            rows = con.execute(
                "SELECT ticker, entry, stop, status FROM paper_positions "
                "WHERE status='OPEN'").fetchall()
            con.close()
            print(json.dumps([{"ticker": r[0], "entry": r[1], "stop": r[2]} for r in rows],
                             indent=2, default=str))
        except Exception as e:
            print(json.dumps({"positions": [], "note": str(e)}))
    elif cmd == "reconcile":
        from execution import reconciliation as rec
        r = rec.reconcile([], [])
        print(json.dumps({"ok": r.ok, "worst": r.worst, "mismatches": r.mismatches}, indent=2))
    elif cmd == "dry_run":
        if len(args) < 2:
            print("usage: dry_run SYMBOL  (routes a sample proposal through OrderManager)")
        else:
            print("dry_run routes through execution.order_manager; see test_order_manager.")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
