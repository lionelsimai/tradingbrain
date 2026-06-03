#!/usr/bin/env python3
"""Forward paper evidence runner.

This is the paper-only lifecycle recorder the live gate can trust later. It
keeps replay/backtest evidence out of the paper evidence path, routes accepted
signals through OrderManager + PaperAdapter, and writes machine-readable files
under reports/forward-paper/.

Commands:
  python3 -m loops.forward_paper_runner --once
  python3 -m loops.forward_paper_runner --premarket
  python3 -m loops.forward_paper_runner --eod
  python3 -m loops.forward_paper_runner --resolve
  python3 -m loops.forward_paper_runner --scorecard
"""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from paths import DATA_DIR, PRICES_DB, REPORTS_DIR


FORWARD_DIR = REPORTS_DIR / "forward-paper"
INTRADAY_SNAPSHOT = DATA_DIR / "intraday_snap.parquet"
MAX_LIVE_QUOTE_AGE_SECONDS = 15 * 60
LIVE_LIKE_QUOTE_SOURCES = {"moomoo:market_snapshot"}
FILES = {
    "signals": "paper_signals.jsonl",
    "orders": "paper_orders.jsonl",
    "fills": "paper_fills.jsonl",
    "positions": "paper_positions.jsonl",
    "exits": "paper_exits.jsonl",
    "scorecard": "paper_scorecard.json",
    "incidents": "paper_incidents.jsonl",
}


@dataclass
class ForwardSignal:
    signal_id: str
    signal_timestamp: str
    signal_source: str
    ticker: str
    strategy: str
    regime: str
    entry_plan: float
    stop: float
    target: float | None
    risk_amount: float
    position_size: int
    quote_at_decision: dict[str, Any]
    spread_bps: float | None
    data_freshness: dict[str, Any]
    status: str
    confidence: float | None = None
    rejection_reason: str | None = None


@dataclass
class PaperOrderRecord:
    order_id: str
    signal_id: str
    broker_paper_order_id: str | None
    ticker: str
    strategy: str
    side: str
    status: str
    submitted_at: str
    stop_attach_status: str
    target_attach_status: str
    broker_response: dict[str, Any] = field(default_factory=dict)


@dataclass
class PaperFillRecord:
    fill_id: str
    order_id: str
    signal_id: str
    ticker: str
    fill_price: float | None
    fill_time: str | None
    filled_qty: float
    partial_fill_status: str
    slippage_bps: float | None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dir(report_dir: Path = REPORTS_DIR) -> Path:
    d = report_dir / "forward-paper"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(kind: str, report_dir: Path = REPORTS_DIR) -> Path:
    return _dir(report_dir) / FILES[kind]


def _read_jsonl(kind: str, report_dir: Path = REPORTS_DIR) -> list[dict[str, Any]]:
    p = _path(kind, report_dir)
    if not p.exists():
        return []
    rows = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def _append(kind: str, row: dict[str, Any], report_dir: Path = REPORTS_DIR) -> None:
    p = _path(kind, report_dir)
    with p.open("a") as f:
        f.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _write_json(name: str, obj: dict[str, Any], report_dir: Path = REPORTS_DIR) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    p = report_dir / name
    p.write_text(json.dumps(obj, indent=2, sort_keys=True, default=str))
    return p


def _candidate_id(c: dict[str, Any]) -> str:
    raw = "|".join([
        date.today().isoformat(),
        str(c.get("ticker") or c.get("symbol") or "").upper(),
        str(c.get("setup") or c.get("strategy") or "UNKNOWN"),
        str(c.get("entry")),
        str(c.get("stop") or c.get("stop_loss")),
    ])
    return "fps_" + hashlib.sha256(raw.encode()).hexdigest()[:16]


def _load_candidates(report_dir: Path = REPORTS_DIR, limit: int = 5) -> list[dict[str, Any]]:
    for name in ("desk-signals.json", "swing-setups.json"):
        p = report_dir / name
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        rows = data.get("buys") or data.get("setups") or data.get("candidates") or []
        out = []
        for r in rows[:limit]:
            ticker = r.get("ticker") or r.get("symbol")
            entry = r.get("entry") or r.get("price")
            stop = r.get("stop") or r.get("stop_loss")
            target = r.get("target") or r.get("t1")
            if not ticker or not entry or not stop:
                continue
            out.append({
                "ticker": str(ticker).upper(),
                "strategy": r.get("strategy") or r.get("setup") or "UNKNOWN",
                "setup": r.get("setup") or r.get("strategy") or "UNKNOWN",
                "entry": float(entry),
                "stop": float(stop),
                "target": float(target) if target else float(entry) * 1.1,
                "confidence": float(r.get("confidence", 0.65)),
                "regime": data.get("regime") or r.get("regime") or "unknown",
                "source": name,
            })
        if out:
            return out
    return []


def _spread_bps(quote: dict[str, Any]) -> float | None:
    bid, ask = quote.get("bid"), quote.get("ask")
    if bid is None or ask is None:
        return None
    mid = (float(bid) + float(ask)) / 2.0
    if mid <= 0:
        return None
    return round((float(ask) - float(bid)) / mid * 10000.0, 3)


def _quote(entry: float) -> dict[str, Any]:
    return {
        "bid": round(entry * 0.999, 4),
        "ask": round(entry * 1.001, 4),
        "last": entry,
        "ts_age_seconds": 2,
        "ts_age_s": 2,
        "avg_dollar_volume": 5e8,
        "tradable": True,
    }


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _parse_utc(value: Any):
    if value is None:
        return None
    try:
        import pandas as pd
        ts = pd.to_datetime(value, utc=True)
        if pd.isna(ts):
            return None
        return ts.to_pydatetime()
    except Exception:
        return None


def _intraday_quote(
    ticker: str,
    *,
    snapshot_path: Path | None = None,
    max_age_seconds: int = MAX_LIVE_QUOTE_AGE_SECONDS,
    now=None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    now_utc = now or datetime.now(timezone.utc)
    snapshot_path = snapshot_path or INTRADAY_SNAPSHOT
    if not snapshot_path.exists():
        return None, {
            "source": "intraday_snapshot",
            "live_like_quote": False,
            "reason": f"{snapshot_path} missing",
        }
    try:
        import pandas as pd
        df = pd.read_parquet(snapshot_path)
    except Exception as exc:
        return None, {
            "source": "intraday_snapshot",
            "live_like_quote": False,
            "reason": f"intraday snapshot unreadable: {exc}",
        }
    if "ticker" not in df.columns:
        return None, {
            "source": "intraday_snapshot",
            "live_like_quote": False,
            "reason": "intraday snapshot missing ticker column",
        }
    rows = df[df["ticker"].astype(str).str.upper() == ticker.upper()].copy()
    if rows.empty:
        return None, {
            "source": "intraday_snapshot",
            "live_like_quote": False,
            "reason": f"no intraday quote for {ticker.upper()}",
        }
    sort_col = "fetched_at_utc" if "fetched_at_utc" in rows.columns else ("ts_utc" if "ts_utc" in rows.columns else None)
    if sort_col:
        rows["_sort_ts"] = rows[sort_col].map(_parse_utc)
        rows = rows.sort_values("_sort_ts")
    row = rows.iloc[-1]
    source = str(row.get("source") or "unknown")
    bid = _float_or_none(row.get("bid"))
    ask = _float_or_none(row.get("ask"))
    last = _float_or_none(row.get("last_price") if "last_price" in row else row.get("last"))
    fetched = _parse_utc(row.get("fetched_at_utc") if "fetched_at_utc" in row else None)
    quote_ts = _parse_utc(row.get("ts_utc") if "ts_utc" in row else None)
    age_base = fetched or quote_ts
    age_seconds = max(0, int((now_utc - age_base).total_seconds())) if age_base else None
    freshness = {
        "source": source,
        "snapshot_path": str(snapshot_path),
        "fetched_at_utc": fetched.isoformat() if fetched else None,
        "quote_ts_utc": quote_ts.isoformat() if quote_ts else None,
        "quote_age_seconds": age_seconds,
        "live_like_quote": source in LIVE_LIKE_QUOTE_SOURCES,
        "required_source_set": sorted(LIVE_LIKE_QUOTE_SOURCES),
    }
    if bid is None or ask is None:
        return None, {**freshness, "reason": "intraday quote missing bid/ask"}
    if bid <= 0 or ask <= 0 or last is None or last <= 0:
        return None, {**freshness, "reason": "intraday quote has non-positive price"}
    if ask < bid:
        return None, {**freshness, "reason": "intraday quote crossed bid/ask"}
    if age_seconds is None:
        return None, {**freshness, "reason": "intraday quote age unknown"}
    if age_seconds > max_age_seconds:
        return None, {**freshness, "reason": f"intraday quote stale ({age_seconds}s > {max_age_seconds}s)"}
    quote = {
        "bid": bid,
        "ask": ask,
        "last": last,
        "ts_age_seconds": age_seconds,
        "ts_age_s": age_seconds,
        "avg_dollar_volume": _float_or_none(row.get("avg_dollar_volume")) or 5e8,
        "tradable": str(row.get("sec_status", "NORMAL")).upper() not in {"SUSPENDED", "HALTED"},
        "source": source,
    }
    return quote, freshness


def _decision_quote(
    candidate: dict[str, Any],
    *,
    require_live_data: bool,
    allow_synthetic_quotes: bool,
    max_quote_age_seconds: int,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    quote, freshness = _intraday_quote(
        candidate["ticker"],
        max_age_seconds=max_quote_age_seconds,
    )
    if quote is not None and (not require_live_data or freshness.get("live_like_quote")):
        return quote, freshness
    if require_live_data:
        reason = freshness.get("reason") or (
            f"quote source {freshness.get('source')} is not live-like; need one of {sorted(LIVE_LIKE_QUOTE_SOURCES)}"
        )
        return None, {**freshness, "live_like_required": True, "reason": reason}
    if allow_synthetic_quotes:
        fallback = _quote(candidate["entry"])
        return fallback, {
            "quote_age_seconds": fallback["ts_age_seconds"],
            "source": "synthetic_paper_quote",
            "live_like_quote": False,
            "synthetic": True,
            "fallback_reason": freshness.get("reason") or f"using synthetic fallback instead of {freshness.get('source')}",
        }
    return None, {**freshness, "reason": freshness.get("reason") or "no usable paper quote"}


def premarket(report_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    """Write a premarket readiness marker; no orders are submitted."""
    from safety import config_guard, risk_policy
    ok, reasons = config_guard.safe_to_trade("paper")
    out = {
        "asof": _now(),
        "stage": "premarket",
        "mode": config_guard.mode(),
        "paper_safe_to_trade": ok,
        "blocking_reasons": reasons,
        "risk_policy_hash": risk_policy.version(),
    }
    _write_json("forward-paper-premarket.json", out, report_dir)
    if not ok:
        _append("incidents", {
            "created_at": _now(),
            "severity": "blocking",
            "category": "system",
            "description": "premarket paper gate blocked",
            "evidence": {"reasons": reasons},
            "blocks_new_entries": True,
            "requires_human_review": True,
            "resolved": False,
            "runbook_step": "Review config_guard and kill switch before paper entries.",
        }, report_dir)
    return out


def run_once(
    report_dir: Path = REPORTS_DIR,
    limit: int = 5,
    *,
    require_live_data: bool = False,
    allow_synthetic_quotes: bool = True,
    max_quote_age_seconds: int = MAX_LIVE_QUOTE_AGE_SECONDS,
) -> dict[str, Any]:
    """Emit today's paper signals and route accepted candidates through paper broker."""
    from execution.order_manager import OrderManager, Proposal
    from execution.paper_adapter import PaperAdapter, PaperConfig

    existing = {r["signal_id"] for r in _read_jsonl("signals", report_dir) if r.get("signal_id")}
    candidates = _load_candidates(report_dir, limit=limit)
    adapter = PaperAdapter(cfg=PaperConfig(partial_fill_prob=0.0, seed=7))
    manager = OrderManager(adapter=adapter, mode="paper")
    processed = []

    for c in candidates:
        sid = _candidate_id(c)
        if sid in existing:
            continue
        quote, freshness = _decision_quote(
            c,
            require_live_data=require_live_data,
            allow_synthetic_quotes=allow_synthetic_quotes,
            max_quote_age_seconds=max_quote_age_seconds,
        )
        if quote is None:
            signal = ForwardSignal(
                signal_id=sid,
                signal_timestamp=_now(),
                signal_source=c["source"],
                ticker=c["ticker"],
                strategy=c["strategy"],
                regime=c["regime"],
                entry_plan=c["entry"],
                stop=c["stop"],
                target=c["target"],
                risk_amount=0.0,
                position_size=0,
                quote_at_decision={},
                spread_bps=None,
                data_freshness=freshness,
                status="rejected",
                confidence=c.get("confidence"),
                rejection_reason="data: " + str(freshness.get("reason", "quote unavailable")),
            )
            _append("signals", asdict(signal), report_dir)
            processed.append(asdict(signal))
            continue
        adapter.set_quote(c["ticker"], quote["bid"], quote["ask"], quote["last"], age_s=float(quote.get("ts_age_s", 0)))
        signal = ForwardSignal(
            signal_id=sid,
            signal_timestamp=_now(),
            signal_source=c["source"],
            ticker=c["ticker"],
            strategy=c["strategy"],
            regime=c["regime"],
            entry_plan=c["entry"],
            stop=c["stop"],
            target=c["target"],
            risk_amount=0.0,
            position_size=0,
            quote_at_decision=quote,
            spread_bps=_spread_bps(quote),
            data_freshness=freshness,
            status="pending",
            confidence=c.get("confidence"),
        )
        prop = Proposal(
            symbol=c["ticker"],
            side="buy",
            strategy=c["strategy"],
            setup=c["setup"],
            entry=c["entry"],
            stop_loss=c["stop"],
            take_profit=c["target"],
            confidence=c["confidence"],
            evidence_source="paper",
            quote=quote,
            current_positions=adapter.get_positions(),
        )
        result = manager.submit(prop, human_approved=True)
        rd = result.risk_decision or {}
        signal.position_size = int(rd.get("suggested_position_size") or 0)
        signal.risk_amount = round(float(rd.get("max_loss_amount") or 0.0), 4)
        signal.status = "accepted" if result.submitted else "rejected"
        signal.rejection_reason = result.rejected_reason
        _append("signals", asdict(signal), report_dir)
        processed.append(asdict(signal))

        if not result.submitted:
            continue
        resp = result.broker_response or {}
        stop_status = "attached" if c["stop"] and resp.get("status") not in {"rejected", "error"} else "missing"
        target_status = "attached" if c["target"] and resp.get("status") not in {"rejected", "error"} else "missing"
        order = PaperOrderRecord(
            order_id=result.client_order_id or sid,
            signal_id=sid,
            broker_paper_order_id=resp.get("client_order_id"),
            ticker=c["ticker"],
            strategy=c["strategy"],
            side="buy",
            status=str(resp.get("status", "unknown")),
            submitted_at=_now(),
            stop_attach_status=stop_status,
            target_attach_status=target_status,
            broker_response=resp,
        )
        _append("orders", asdict(order), report_dir)
        if resp.get("filled_qty"):
            fill_price = resp.get("avg_price")
            slippage = None
            if fill_price:
                slippage = round((float(fill_price) - quote["ask"]) / quote["ask"] * 10000.0, 3)
            fill = PaperFillRecord(
                fill_id="fill_" + hashlib.sha256((order.order_id + sid).encode()).hexdigest()[:12],
                order_id=order.order_id,
                signal_id=sid,
                ticker=c["ticker"],
                fill_price=float(fill_price) if fill_price is not None else None,
                fill_time=_now(),
                filled_qty=float(resp.get("filled_qty") or 0),
                partial_fill_status="partial" if resp.get("status") == "partially_filled" else "full",
                slippage_bps=slippage,
            )
            _append("fills", asdict(fill), report_dir)
            _append("positions", {
                "signal_id": sid,
                "ticker": c["ticker"],
                "strategy": c["strategy"],
                "opened_at": date.today().isoformat(),
                "entry": fill.fill_price,
                "planned_entry": c["entry"],
                "stop": c["stop"],
                "target": c["target"],
                "qty": fill.filled_qty,
                "status": "open",
                "reconciliation_status": "paper_internal",
            }, report_dir)
            if stop_status != "attached":
                _append("incidents", {
                    "created_at": _now(),
                    "severity": "critical",
                    "category": "execution",
                    "symbol": c["ticker"],
                    "strategy": c["strategy"],
                    "description": "paper fill without attached stop",
                    "evidence": {"signal_id": sid, "order_id": order.order_id},
                    "blocks_new_entries": True,
                    "requires_human_review": True,
                    "resolved": False,
                    "runbook_step": "Attach stop or close the paper position; verify protective order flow.",
                }, report_dir)

    card = scorecard(report_dir)
    return {"processed": len(processed), "signals": processed, "scorecard": card}


def _latest_bars(ticker: str, opened_at: str) -> list[dict[str, Any]]:
    try:
        import duckdb
        con = duckdb.connect(str(PRICES_DB), read_only=True)
        rows = con.execute(
            "SELECT date, open, high, low, close FROM prices WHERE ticker=? AND date>=? ORDER BY date",
            [ticker, opened_at],
        ).fetchall()
        con.close()
    except Exception:
        rows = []
    return [
        {"date": str(r[0]), "open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4])}
        for r in rows
    ]


def resolve(report_dir: Path = REPORTS_DIR, max_hold_days: int = 20) -> dict[str, Any]:
    positions = _read_jsonl("positions", report_dir)
    exited = {r["signal_id"] for r in _read_jsonl("exits", report_dir) if r.get("signal_id")}
    resolved = []
    for p in positions:
        sid = p.get("signal_id")
        if not sid or sid in exited or p.get("status") != "open":
            continue
        bars = _latest_bars(str(p["ticker"]), str(p["opened_at"]))
        if len(bars) < 2:
            continue
        entry = float(p["entry"])
        stop = float(p["stop"])
        target = float(p["target"]) if p.get("target") is not None else None
        risk = entry - stop
        if risk <= 0:
            continue
        exit_reason = None
        exit_price = None
        exit_date = None
        for idx, bar in enumerate(bars[1:], start=1):
            if float(bar["low"]) <= stop:
                exit_reason, exit_price, exit_date = "stop", stop, bar["date"]
                break
            if target is not None and float(bar["high"]) >= target:
                exit_reason, exit_price, exit_date = "target", target, bar["date"]
                break
            if idx >= max_hold_days:
                exit_reason, exit_price, exit_date = "timeout", float(bar["close"]), bar["date"]
                break
        if exit_reason is None:
            continue
        r_mult = round((float(exit_price) - entry) / risk, 4)
        rec = {
            "signal_id": sid,
            "ticker": p["ticker"],
            "strategy": p.get("strategy"),
            "exit_reason": exit_reason,
            "exit_price": round(float(exit_price), 4),
            "exit_time": exit_date,
            "r_multiple": r_mult,
            "hold_days": len(bars[1:]),
            "thesis_review": "resolved by deterministic forward-paper rule",
            "reconciliation_status": "paper_internal",
        }
        _append("exits", rec, report_dir)
        resolved.append(rec)
    card = scorecard(report_dir)
    return {"resolved": len(resolved), "exits": resolved, "scorecard": card}


def _max_consecutive_losses(rs: list[float]) -> int:
    best = cur = 0
    for r in rs:
        if r < 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _drawdown(rs: list[float]) -> float:
    equity = peak = 0.0
    worst = 0.0
    for r in rs:
        equity += r
        peak = max(peak, equity)
        worst = min(worst, equity - peak)
    return round(worst, 4)


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, int((pct / 100.0) * len(ordered) + 0.999999) - 1))
    return round(ordered[idx], 4)


def _win_rate(rs: list[float]) -> float | None:
    return round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 2) if rs else None


def _r_summary(rs: list[float]) -> dict[str, Any]:
    avg = round(sum(rs) / len(rs), 4) if rs else None
    return {
        "n": len(rs),
        "win_rate": _win_rate(rs),
        "average_R": avg,
        "median_R": _median(rs),
        "expectancy_R": avg,
        "max_drawdown_R": _drawdown(rs),
        "max_consecutive_losses": _max_consecutive_losses(rs),
    }


def _confidence_band(confidence: Any) -> str:
    try:
        c = float(confidence)
    except Exception:
        return "unknown"
    if c < 0.60:
        return "<0.60"
    if c < 0.70:
        return "0.60-0.69"
    if c < 0.80:
        return "0.70-0.79"
    return ">=0.80"


def _empty_signal_group() -> dict[str, Any]:
    return {
        "signals": 0,
        "accepted": 0,
        "rejected": 0,
        "resolved": 0,
        "win_rate": None,
        "average_R": None,
        "median_R": None,
        "expectancy_R": None,
        "max_drawdown_R": 0.0,
        "max_consecutive_losses": 0,
    }


def _group_signal_performance(
    signals: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    field: str,
    *,
    signal_by_id: dict[Any, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    rs_by_group: dict[str, list[float]] = {}
    for signal in signals:
        key = str(signal.get(field) or "unknown")
        row = grouped.setdefault(key, _empty_signal_group())
        row["signals"] += 1
        if signal.get("status") == "accepted":
            row["accepted"] += 1
        if signal.get("status") == "rejected":
            row["rejected"] += 1
    for exit_row in exits:
        sig = signal_by_id.get(exit_row.get("signal_id")) or {}
        key = str(exit_row.get(field) or sig.get(field) or "unknown")
        grouped.setdefault(key, _empty_signal_group())
        try:
            rs_by_group.setdefault(key, []).append(float(exit_row.get("r_multiple") or 0.0))
        except Exception:
            continue
    for key, rs in rs_by_group.items():
        row = grouped.setdefault(key, _empty_signal_group())
        row.update(_r_summary(rs))
        row["resolved"] = len(rs)
    return grouped


def _confidence_band_breakdown(
    signals: list[dict[str, Any]],
    exits: list[dict[str, Any]],
    *,
    signal_by_id: dict[Any, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    rs_by_group: dict[str, list[float]] = {}
    for signal in signals:
        key = _confidence_band(signal.get("confidence"))
        row = grouped.setdefault(key, _empty_signal_group())
        row["signals"] += 1
        if signal.get("status") == "accepted":
            row["accepted"] += 1
        if signal.get("status") == "rejected":
            row["rejected"] += 1
    for exit_row in exits:
        sig = signal_by_id.get(exit_row.get("signal_id")) or {}
        key = _confidence_band(sig.get("confidence"))
        grouped.setdefault(key, _empty_signal_group())
        try:
            rs_by_group.setdefault(key, []).append(float(exit_row.get("r_multiple") or 0.0))
        except Exception:
            continue
    for key, rs in rs_by_group.items():
        row = grouped.setdefault(key, _empty_signal_group())
        row.update(_r_summary(rs))
        row["resolved"] = len(rs)
    return grouped


def _slippage_summary(slippages: list[float]) -> dict[str, Any]:
    return {
        "n": len(slippages),
        "average_bps": round(sum(slippages) / len(slippages), 3) if slippages else None,
        "median_bps": _median(slippages),
        "p95_bps": _percentile(slippages, 95),
        "max_bps": round(max(slippages), 4) if slippages else None,
        "over_25bps": sum(1 for v in slippages if v > 25.0),
        "over_50bps": sum(1 for v in slippages if v > 50.0),
    }


def _ledger_paper_summary() -> dict[str, Any]:
    try:
        import duckdb
        from paths import KNOWLEDGE_DB
        con = duckdb.connect(str(KNOWLEDGE_DB))
        rows = con.execute(
            "SELECT status, realized_R FROM signal_ledger WHERE COALESCE(source, 'paper')='paper'"
        ).fetchall()
        con.close()
    except Exception:
        rows = []
    resolved = [float(r[1]) for r in rows if r[1] is not None and str(r[0]).lower() in {"won", "lost"}]
    open_count = sum(1 for r in rows if str(r[0]).lower() == "open")
    return {
        "resolved": len(resolved),
        "open": open_count,
        "r_multiples": resolved,
    }


def scorecard(report_dir: Path = REPORTS_DIR) -> dict[str, Any]:
    signals = _read_jsonl("signals", report_dir)
    orders = _read_jsonl("orders", report_dir)
    fills = _read_jsonl("fills", report_dir)
    positions = _read_jsonl("positions", report_dir)
    exits = _read_jsonl("exits", report_dir)
    incidents = _read_jsonl("incidents", report_dir)
    filled_ids = {f.get("signal_id") for f in fills}
    exited_ids = {e.get("signal_id") for e in exits}
    open_positions = [p for p in positions if p.get("signal_id") not in exited_ids]
    signal_by_id = {s.get("signal_id"): s for s in signals if s.get("signal_id")}
    ledger = _ledger_paper_summary() if report_dir == REPORTS_DIR else {"resolved": 0, "open": 0, "r_multiples": []}
    rs = [float(e.get("r_multiple") or 0.0) for e in exits] + list(ledger["r_multiples"])
    slippages = [float(f["slippage_bps"]) for f in fills if f.get("slippage_bps") is not None]
    resolved_count = len(exits) + int(ledger["resolved"])
    open_count = len(open_positions) + int(ledger["open"])
    forward_signal_count = max(len(signals), len(positions) + len(exits))
    total_signals = forward_signal_count + int(ledger["resolved"]) + int(ledger["open"])

    def breakdown(field: str) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in signals:
            key = str(s.get(field) or "unknown")
            out[key] = out.get(key, 0) + 1
        return out

    def quote_source_breakdown() -> dict[str, int]:
        out: dict[str, int] = {}
        for s in signals:
            freshness = s.get("data_freshness") or {}
            key = str(freshness.get("source") or "unknown")
            out[key] = out.get(key, 0) + 1
        return out

    def _live_like_signal(signal_id: Any) -> bool:
        sig = signal_by_id.get(signal_id) or {}
        freshness = sig.get("data_freshness") or {}
        return bool(freshness.get("live_like_quote"))

    live_like_signal_count = sum(1 for s in signals if (s.get("data_freshness") or {}).get("live_like_quote"))
    synthetic_quote_signal_count = sum(1 for s in signals if (s.get("data_freshness") or {}).get("synthetic"))
    live_like_resolved = sum(1 for e in exits if _live_like_signal(e.get("signal_id")))

    avg_r = round(sum(rs) / len(rs), 4) if rs else None
    fill_rate = round(100.0 * len(fills) / len(orders), 2) if orders else None
    partial_fill_rate = round(100.0 * sum(1 for f in fills if f.get("partial_fill_status") == "partial") / len(fills), 2) if fills else None
    missed_fill_rate = round(100.0 * max(0, len(orders) - len(fills)) / len(orders), 2) if orders else None
    card = {
        "evidence_source": "paper",
        "asof": _now(),
        "total_signals": total_signals,
        "accepted_signals": sum(1 for s in signals if s.get("status") == "accepted"),
        "rejected_signals": sum(1 for s in signals if s.get("status") == "rejected"),
        "filled_orders": len(fills),
        "missed_fills": max(0, len(orders) - len(fills)),
        "partial_fills": sum(1 for f in fills if f.get("partial_fill_status") == "partial"),
        "resolved_trades": resolved_count,
        "open": open_count,
        "resolved": resolved_count,
        "win_rate": round(100.0 * sum(1 for r in rs if r > 0) / len(rs), 2) if rs else None,
        "average_R": avg_r,
        "median_R": round(statistics.median(rs), 4) if rs else None,
        "expectancy_R": avg_r,
        "slippage_average_bps": round(sum(slippages) / len(slippages), 3) if slippages else None,
        "slippage_summary": _slippage_summary(slippages),
        "fill_quality": {
            "fill_rate_pct": fill_rate,
            "partial_fill_rate_pct": partial_fill_rate,
            "missed_fill_rate_pct": missed_fill_rate,
            "filled_orders": len(fills),
            "orders": len(orders),
        },
        "max_drawdown_R": _drawdown(rs),
        "max_consecutive_losses": _max_consecutive_losses(rs),
        "strategy_breakdown": breakdown("strategy"),
        "regime_breakdown": breakdown("regime"),
        "ticker_breakdown": breakdown("ticker"),
        "performance_by_strategy": _group_signal_performance(
            signals, exits, "strategy", signal_by_id=signal_by_id),
        "performance_by_regime": _group_signal_performance(
            signals, exits, "regime", signal_by_id=signal_by_id),
        "performance_by_ticker": _group_signal_performance(
            signals, exits, "ticker", signal_by_id=signal_by_id),
        "quote_source_breakdown": quote_source_breakdown(),
        "live_like_signal_count": live_like_signal_count,
        "synthetic_quote_signal_count": synthetic_quote_signal_count,
        "live_like_resolved_trades": live_like_resolved,
        "confidence_band_breakdown": _confidence_band_breakdown(
            signals, exits, signal_by_id=signal_by_id),
        "backtest_versus_paper_gap": None,
        "drift_status": "insufficient_forward_paper" if resolved_count < 50 else "ready_for_drift_review",
        "demotion_recommendations": ["collect more forward paper evidence"] if resolved_count < 50 else [],
        "open_incidents": [i for i in incidents if not i.get("resolved")],
        "overall": {"n": resolved_count, "expectancy_R": avg_r} if resolved_count else {"n": 0},
        "verdict": (
            f"INSUFFICIENT PAPER EVIDENCE ({resolved_count} paper trades). No paper gating."
            if resolved_count < 50 else f"PAPER EVIDENCE READY FOR REVIEW ({resolved_count} trades)."
        ),
        "legacy_signal_ledger_paper": {
            "resolved": int(ledger["resolved"]),
            "open": int(ledger["open"]),
            "note": "Included only when source='paper'; replay rows are excluded.",
        },
        "methodology_caveat": (
            "Forward paper records here are paper-only. Replay/backtest rows are not counted. "
            "Live-like paper readiness requires resolved trades whose decision quotes came "
            "from fresh approved intraday sources, currently moomoo:market_snapshot."
        ),
    }
    _path("scorecard", report_dir).write_text(json.dumps(card, indent=2, sort_keys=True, default=str))
    _write_json("forward-paper-scorecard.json", card, report_dir)
    _write_json("scorecard-paper.json", card, report_dir)
    return card


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--premarket", action="store_true")
    ap.add_argument("--eod", action="store_true")
    ap.add_argument("--resolve", action="store_true")
    ap.add_argument("--scorecard", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--require-live-data", action="store_true",
                    help="reject paper signals unless a fresh approved live-like quote is available")
    ap.add_argument("--max-quote-age-seconds", type=int, default=MAX_LIVE_QUOTE_AGE_SECONDS)
    args = ap.parse_args(argv)

    if args.premarket:
        print(json.dumps(premarket(), indent=2, default=str))
    if args.once:
        print(json.dumps(run_once(
            limit=args.limit,
            require_live_data=args.require_live_data,
            max_quote_age_seconds=args.max_quote_age_seconds,
        ), indent=2, default=str))
    if args.eod or args.resolve:
        print(json.dumps(resolve(), indent=2, default=str))
    if args.scorecard or not any([args.once, args.premarket, args.eod, args.resolve]):
        print(json.dumps(scorecard(), indent=2, default=str))


if __name__ == "__main__":
    main()
