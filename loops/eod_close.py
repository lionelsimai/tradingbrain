#!/usr/bin/env python3
"""End-of-day close — runs ~30 min after US market close.

Steps:
  1. Refresh prices for today
  2. Mark paper positions (stop/target/timeout)
  3. Open new positions from today's swing setups (respecting risk cap)
  4. Compose a compact end-of-day P&L message
"""
from __future__ import annotations
import subprocess, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
KB = ROOT / "data" / "knowledge.duckdb"
PY = sys.executable

def run(cmd, timeout=300):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(ROOT))
        return r.returncode, (r.stdout or "")[-400:]
    except Exception as e:
        return -1, str(e)

def main():
    pipeline = [
        [PY, "-m", "scripts.backfill_10y", "--years", "1"],
        [PY, "-m", "scripts.ingest.earnings_calendar"],
        [PY, "-m", "scripts.ingest.intraday_snap"],
        [PY, "scripts/momentum.py"],
        [PY, "-m", "scripts.signals.swing_setup", "--top", "20"],
        [PY, "-m", "loops.signal_tracker", "resolve"],
        [PY, "-m", "loops.signal_tracker", "scorecard"],
        [PY, "-m", "loops.reconcile"],
        [PY, "-m", "scripts.brain.hmm_regime"],
        [PY, "-m", "scripts.brain.circuit_breakers"],
        [PY, "-m", "scripts.brain.allocation"],
        [PY, "scripts/paper_broker.py"],
        [PY, "scripts/broker_alpaca.py"],
    ]
    for cmd in pipeline:
        rc, out = run(cmd)
        tag = "OK" if rc == 0 else f"FAIL({rc})"
        print(f"  [{tag}] {' '.join(cmd[2:] or cmd[1:])}")
    con = duckdb.connect(str(KB), read_only=True)
    acc = con.execute(
        "SELECT snapshot_date, equity, n_open AS open_count, total_risk AS open_risk_R,"
        " closed AS closed_today, realized_R, unrealized_R"
        " FROM paper_account ORDER BY snapshot_date DESC LIMIT 1"
    ).fetchone()
    today_close = con.execute(
        "SELECT ticker, status, exit, pnl_R, pnl_pct"
        " FROM paper_positions WHERE closed_at = (SELECT MAX(snapshot_date) FROM paper_account)"
        " ORDER BY pnl_R DESC"
    ).fetchall()
    open_pos = con.execute(
        "SELECT ticker, entry, stop, target, opened_at FROM paper_positions WHERE status='OPEN'"
        " ORDER BY opened_at"
    ).fetchall()
    now = datetime.now(ZoneInfo("Asia/Singapore"))
    et = now.astimezone(ZoneInfo("America/New_York"))
    lines = [
        f"📊 EOD · {now:%H:%M} SGT ({et:%H:%M} ET)",
        f"Equity ${acc[1]:,.0f}  ·  Open {acc[2]}  ·  Risk {acc[3]:.2%}",
        f"Today: realized {acc[5]:+.2f}R  ·  unrealized {acc[6]:+.2f}R  ·  closed {acc[4]}",
    ]
    if today_close:
        lines.append("📍 Closed today:")
        for t, st, ex, r, pct in today_close[:5]:
            tag = "🎯" if "TARGET" in st else "🛑" if "STOP" in st else "⏱"
            lines.append(f"  {tag} {t}  exit ${ex:.2f}  {r:+.2f}R ({pct:+.2f}%)")
    if open_pos:
        lines.append("📌 Open:")
        for t, e, s, tg, _ in open_pos[:5]:
            lines.append(f"  {t}  entry ${e:.2f} → stop ${s:.2f} / target ${tg:.2f}")
    lines.append("🔗 https://lionelsim.zo.space/portfolio")
    out = "\n".join(lines)
    (ROOT / "reports" / "eod-latest.txt").write_text(out)
    print(out)

if __name__ == "__main__":
    main()
