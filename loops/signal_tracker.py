#!/usr/bin/env python3
"""Live forward-test feedback loop — the brain's real scorecard.

Closes the recursive-learning gap: records every doctrine BUY the brain emits,
marks each to market bar-by-bar (stop/T1/timeout), computes realized R, and
scores LIVE expectancy vs the BACKTEST claim (drift detection).

Subcommands:
  emit       — log today's desk-signals buys into the ledger (idempotent)
  resolve    — advance every open signal on new price data; close on stop/target/timeout
  scorecard  — aggregate resolved trades; write reports/live-scorecard.json
"""
from __future__ import annotations
import json, sys, uuid
from datetime import datetime, timezone, date
from pathlib import Path
import duckdb

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT))
KB = ROOT / "data" / "knowledge.duckdb"
PRICES = ROOT / "data" / "prices.duckdb"
DESK = ROOT / "reports" / "desk-signals.json"
OUT = ROOT / "reports" / "live-scorecard.json"
HOLD_CAP = 20  # trading days max hold

_LEDGER_DDL = """
CREATE TABLE IF NOT EXISTS signal_ledger (
    id VARCHAR PRIMARY KEY, emit_date DATE, emit_ts TIMESTAMP, ticker VARCHAR,
    setup VARCHAR, grade VARCHAR, regime VARCHAR, entry DOUBLE, stop DOUBLE,
    t1 DOUBLE, t2 DOUBLE, rr DOUBLE, risk_per_share DOUBLE, status VARCHAR,
    exit_date DATE, exit_price DOUBLE, realized_R DOUBLE, mfe_R DOUBLE,
    mae_R DOUBLE, hold_days INTEGER, exit_reason VARCHAR, source VARCHAR DEFAULT 'paper'
)
"""


def _ensure_schema(con):
    con.execute(_LEDGER_DDL)


def _conn():
    con = duckdb.connect(str(KB))
    _ensure_schema(con)
    return con


def _forward_source() -> str:
    try:
        from safety import config_guard
        return "live" if config_guard.mode() == "live" else "paper"
    except Exception:
        return "paper"


def emit():
    """Log today's BUY signals from desk-signals.json into the ledger."""
    if not DESK.exists():
        print("no desk-signals.json; run desk_signals first"); return
    d = json.loads(DESK.read_text())
    buys = d.get("buys", [])
    con = _conn()
    source = _forward_source()
    n = 0
    for b in buys:
        tkr = b["ticker"]
        # one open signal per ticker at a time
        existing = con.execute(
            "SELECT COUNT(*) FROM signal_ledger WHERE ticker=? AND status='open'", [tkr]
        ).fetchone()[0]
        if existing:
            continue
        rps = b.get("risk_per_share") or (b.get("entry", 0) - b.get("stop", 0))
        if not rps or rps <= 0:
            continue
        sid = f"sig_{date.today():%Y%m%d}_{tkr}_{uuid.uuid4().hex[:6]}"
        # Real point-in-time regime label (fixes F9): prefer an explicit regime
        # on the signal, else classify today's market from the broad index.
        regime = d.get("regime")
        if not regime:
            try:
                from scripts.brain.regime_label import regime_at
                regime = regime_at(date.today())
            except Exception:
                regime = "unknown"
        con.execute("""INSERT INTO signal_ledger
            (id, emit_date, emit_ts, ticker, setup, grade, regime, entry, stop, t1, t2, rr, risk_per_share, status, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', ?)""",
            [sid, date.today(), datetime.now(timezone.utc), tkr, b.get("setup"), b.get("grade"),
             regime, b.get("entry"), b.get("stop"), b.get("t1"), b.get("t2"),
             b.get("rr"), rps, source])
        n += 1
    con.close()
    print(f"emit: {n} new {source} signals logged ({len(buys)} buys in desk-signals)")


def resolve():
    """Advance every open signal on price data using the shared trade_sim
    scale-out exit (50% at T1, breakeven runner, T2/stop/timeout) — identical
    to calibration and research, so live/replay/backtest are comparable."""
    from backtest import trade_sim
    con = _conn()
    px = duckdb.connect(str(PRICES), read_only=True)
    opens = con.execute("SELECT * FROM signal_ledger WHERE status='open'").fetchdf()
    closed = 0
    for _, s in opens.iterrows():
        bars = px.execute(
            "SELECT date, open, high, low, close FROM prices WHERE ticker=? AND date>? ORDER BY date",
            [s["ticker"], s["emit_date"]]).fetchdf()
        if len(bars) < 2:
            continue
        t2 = s["t2"] if s.get("t2") is not None else s["t1"] + (s["t1"] - s["entry"])
        plan = trade_sim.Plan(entry=float(s["entry"]), stop=float(s["stop"]),
                              t1=float(s["t1"]), t2=float(t2))
        if plan.risk <= 0:
            continue
        sim = trade_sim.simulate(bars, plan, timeout=HOLD_CAP, costs_R=0.0, scale_out=True)
        if sim["exit"] == "invalid":
            continue
        hold_bars = sim["hold"]
        win = bars.iloc[:hold_bars]
        rps = plan.risk
        mfe = float(((win["high"] - plan.entry) / rps).max())
        mae = float(((win["low"] - plan.entry) / rps).min())
        exit_date = bars["date"].iloc[hold_bars - 1]
        realized = sim["r"]
        exit_price = plan.entry + realized * rps
        hold = (exit_date - s["emit_date"]).days
        status = "won" if realized > 0 else "lost"
        con.execute("""UPDATE signal_ledger SET status=?, exit_date=?, exit_price=?,
            realized_R=?, mfe_R=?, mae_R=?, hold_days=?, exit_reason=? WHERE id=?""",
            [status, exit_date, round(float(exit_price), 2), round(float(realized), 3),
             round(mfe, 3), round(mae, 3), int(hold), sim["exit"], s["id"]])
        closed += 1
    con.close(); px.close()
    print(f"resolve: {closed} signals closed (trade_sim scale-out)")


def scorecard():
    """Aggregate resolved trades; compare LIVE vs BACKTEST expectancy."""
    con = _conn()
    res = con.execute("SELECT * FROM signal_ledger WHERE status IN ('won','lost')").fetchdf()
    openn = con.execute("SELECT COUNT(*) FROM signal_ledger WHERE status='open'").fetchone()[0]
    open_by_source = dict(con.execute(
        "SELECT COALESCE(source, 'paper') AS source, COUNT(*) FROM signal_ledger "
        "WHERE status='open' GROUP BY 1").fetchall())
    con.close()

    # backtest expectancy for drift comparison
    bt = {}
    cr = ROOT / "reports" / "calibration.json"
    if cr.exists():
        for k, v in json.loads(cr.read_text()).get("calibration", {}).items():
            bt[k] = v.get("expectancy_R")

    def agg(df):
        n = len(df)
        if n == 0:
            return {"n": 0}
        wins = (df["realized_R"] > 0).sum()
        exp = float(df["realized_R"].mean())
        gp = df.loc[df["realized_R"] > 0, "realized_R"].sum()
        gl = abs(df.loc[df["realized_R"] < 0, "realized_R"].sum())
        return {
            "n": int(n), "win_rate": round(100*wins/n, 1),
            "expectancy_R": round(exp, 3),
            "avg_win_R": round(float(df.loc[df["realized_R"]>0,"realized_R"].mean() or 0),2),
            "avg_loss_R": round(float(df.loc[df["realized_R"]<0,"realized_R"].mean() or 0),2),
            "profit_factor": round(gp/gl, 2) if gl else None,
            "avg_hold_days": round(float(df["hold_days"].mean()),1),
        }

    def source_df(source: str):
        if "source" not in res.columns:
            return res.iloc[0:0]
        return res[res["source"] == source]

    def grouped(df):
        by_setup = {}
        if len(df):
            for setup, g in df.groupby("setup"):
                a = agg(g)
                a["backtest_expectancy_R"] = bt.get(setup)
                if a.get("expectancy_R") is not None and bt.get(setup) is not None:
                    a["drift_R"] = round(a["expectancy_R"] - bt[setup], 3)
                by_setup[setup] = a
        by_grade = {str(k): agg(g) for k, g in df.groupby("grade")} if len(df) else {}
        return by_setup, by_grade

    def source_report(source: str) -> dict:
        df = source_df(source)
        by_setup, by_grade = grouped(df)
        return {
            "evidence_source": source,
            "asof": datetime.now(timezone.utc).isoformat(),
            "resolved": int(len(df)),
            "open": int(open_by_source.get(source, 0) or 0),
            "overall": agg(df),
            "by_setup": by_setup,
            "by_grade": by_grade,
            "verdict": _source_verdict(source, agg(df), int(len(df))),
        }

    live_res = source_df("live")
    paper_res = source_df("paper")
    replay_res = source_df("replay")
    overall = agg(res)
    overall_live = agg(live_res)
    overall_paper = agg(paper_res)
    overall_replay = agg(replay_res)
    by_setup, by_grade = grouped(res)

    for source in ("live", "paper", "replay"):
        (ROOT / "reports" / f"scorecard-{source}.json").write_text(
            json.dumps(source_report(source), indent=2, default=str))

    out = {
        "evidence_source": "combined",
        "asof": datetime.now(timezone.utc).isoformat(),
        "resolved": int(len(res)), "open": int(openn),
        "n_live": int(len(live_res)), "n_paper": int(len(paper_res)),
        "n_replay": int(len(replay_res)),
        "overall": overall, "overall_live": overall_live,
        "overall_paper": overall_paper, "overall_replay": overall_replay,
        "by_setup": by_setup, "by_grade": by_grade,
        "verdict": _combined_verdict(overall_live, len(live_res), overall_paper,
                                     len(paper_res), len(replay_res), overall_replay),
        "methodology_caveat": (
            "Combined scorecard is for display/diagnostics only. Live, paper, and replay "
            "reports are written separately as scorecard-live.json, scorecard-paper.json, "
            "and scorecard-replay.json. Replay is survivorship-biased research evidence; "
            "paper is forward sandbox evidence; live is real-capital evidence."
        ),
    }
    OUT.write_text(json.dumps(out, indent=2, default=str))
    print(f"scorecard: {len(res)} resolved ({len(live_res)} live, {len(paper_res)} paper, "
          f"{len(replay_res)} replay), {openn} open -> {OUT}")
    if overall_paper.get("n"):
        print(f"  PAPER expectancy {overall_paper['expectancy_R']:+.3f}R | "
              f"win {overall_paper['win_rate']}% | PF {overall_paper.get('profit_factor')}")
    elif overall_replay.get("n"):
        print(f"  REPLAY expectancy {overall_replay['expectancy_R']:+.3f}R | "
              f"win {overall_replay['win_rate']}% | PF {overall_replay.get('profit_factor')}")
    return out


def _source_verdict(source: str, overall: dict, n: int) -> str:
    if source == "live":
        if n < 20:
            return f"INSUFFICIENT LIVE EVIDENCE ({n} live trades). No live gating."
        e = overall.get("expectancy_R", 0)
        if e > 0.05:
            return f"LIVE EDGE CONFIRMED ({e:+.3f}R over {n} live trades)."
        if e > -0.05:
            return f"LIVE EDGE FLAT ({e:+.3f}R over {n} live trades)."
        return f"LIVE EDGE NEGATIVE ({e:+.3f}R over {n} live trades) — STOP and re-examine."
    if source == "paper":
        if n < 50:
            return f"INSUFFICIENT PAPER EVIDENCE ({n} paper trades). No paper gating."
        e = overall.get("expectancy_R", 0)
        if e > 0.05:
            return f"PAPER EDGE POSITIVE ({e:+.3f}R over {n} paper trades)."
        if e > -0.05:
            return f"PAPER EDGE FLAT ({e:+.3f}R over {n} paper trades)."
        return f"PAPER EDGE NEGATIVE ({e:+.3f}R over {n} paper trades) — STOP and re-examine."
    e = overall.get("expectancy_R", 0)
    if n < 20:
        return f"INSUFFICIENT REPLAY SAMPLE ({n} replay trades)."
    return f"REPLAY-BASED, NOT FORWARD ({e:+.3f}R over {n} replay trades)."


def _combined_verdict(overall_live, n_live, overall_paper, n_paper, n_replay, overall_replay):
    # Only claim a LIVE edge once there is a real live sample.
    if n_live >= 20:
        e = overall_live.get("expectancy_R", 0)
        if e > 0.05:
            return f"LIVE EDGE CONFIRMED ({e:+.3f}R over {n_live} live trades)."
        if e > -0.05:
            return f"LIVE EDGE FLAT ({e:+.3f}R over {n_live} live trades)."
        return f"LIVE EDGE NEGATIVE ({e:+.3f}R over {n_live} live trades) — STOP and re-examine."
    if n_paper >= 50:
        e = overall_paper.get("expectancy_R", 0)
        return f"PAPER-BASED, NOT LIVE ({e:+.3f}R over {n_paper} paper trades; only {n_live} live)."
    e = overall_replay.get("expectancy_R", 0)
    if n_replay < 20:
        return f"INSUFFICIENT SAMPLE ({n_live} live / {n_replay} replay) — keep tracking."
    return (f"REPLAY-BASED, NOT LIVE ({e:+.3f}R over {n_replay} replay trades; only {n_live} "
            f"true live). Indicative recent-regime read — accumulate live fills before trusting.")





def backfill(months: int = 9):
    """Replay the live detector point-in-time over recent history and store each
    as an open signal with the STRUCTURAL trade_sim plan — identical plan + exit
    to calibration, so the only differences vs the 30y backtest are recent regime
    and sample window (genuine drift), not exit-rule artifacts. source='replay';
    true 'live' signals accumulate separately from today forward."""
    import pandas as pd, numpy as np, yaml
    from datetime import timedelta
    from scripts.signals.swing_setup import compute_features, detect_at
    from backtest import trade_sim
    UNIV = yaml.safe_load((ROOT / "config" / "universe.yaml").read_text())
    universe = {t for cat in UNIV["universe"].values() for t in cat if not t.endswith("-USD")}
    px = duckdb.connect(str(PRICES), read_only=True)
    con = _conn()
    con.execute("DELETE FROM signal_ledger WHERE source='replay'")
    spy = px.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker='SPY' ORDER BY date").fetchdf()
    spy["date"] = pd.to_datetime(spy["date"])
    end = pd.to_datetime(px.execute("SELECT MAX(date) FROM prices").fetchone()[0])
    start = end - timedelta(days=months * 30)
    db_tickers = [r[0] for r in px.execute("SELECT DISTINCT ticker FROM prices WHERE ticker NOT IN ('SPY','QQQ','SMH')").fetchall()]
    tickers = sorted(set(db_tickers) & universe) or db_tickers

    def grade_of(score: float) -> str:
        return "A" if score >= 0.75 else ("B" if score >= 0.60 else "C")

    n_emit = 0
    for t in tickers:
        df = px.execute("SELECT date, open, high, low, close, volume FROM prices WHERE ticker=? ORDER BY date", [t]).fetchdf()
        if len(df) < 270:
            continue
        df["date"] = pd.to_datetime(df["date"]); df = df.reset_index(drop=True)
        f = compute_features(df, spy)
        # weekly (~every 3 trading days) decision rows within the recent window,
        # leaving room for the forward hold window.
        mask = (df["date"] >= start) & (df["date"] <= end - timedelta(days=25))
        idxs = [i for i in df.index[mask] if i >= 251][::3]
        for i in idxs:
            d = detect_at(f, i, clenow_rank=None)
            if d.get("setup", "NONE") == "NONE":
                continue
            row = f.iloc[i]; a = float(row["atr14"])
            if not np.isfinite(a) or a <= 0:
                continue
            px_i = float(df["close"].iloc[i])
            plan = trade_sim.plan_from_levels(
                px_i, a,
                swing_low_10=float(row["swing_low_10"]), swing_high_20=float(row["swing_high_20"]),
                swing_high_60=float(row["swing_high_60"]), swing_low_20=float(row["swing_low_20"]),
                hi252=float(row["hi252"]))
            if plan.risk <= 0:
                continue
            rr = (plan.t1 - plan.entry) / plan.risk
            dt = df["date"].iloc[i]
            sid = f"rep_{dt:%Y%m%d}_{t}"
            con.execute("""INSERT OR REPLACE INTO signal_ledger
                (id, emit_date, emit_ts, ticker, setup, grade, regime, entry, stop, t1, t2, rr, risk_per_share, status, source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?, 'open', 'replay')""",
                [sid, dt.date(), datetime.now(timezone.utc), t, d["setup"], grade_of(d.get("score", 0)),
                 "replay", round(plan.entry, 2), round(plan.stop, 2), round(plan.t1, 2),
                 round(plan.t2, 2), round(rr, 2), round(plan.risk, 4)])
            n_emit += 1
    con.close(); px.close()
    print(f"backfill: {n_emit} replay signals over {months}mo (structural trade_sim plan)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "scorecard"
    {"emit": emit, "resolve": resolve, "scorecard": scorecard, "backfill": backfill}.get(cmd, scorecard)()
