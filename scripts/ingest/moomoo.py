#!/usr/bin/env python3
"""moomoo OpenAPI real-time US equity snapshot ingest.

This is market-data only. It connects to a local moomoo OpenD instance, fetches
US equity market snapshots, and writes the same intraday snap parquet that the
signal engine already reads:

    data/intraday_snap.parquet
    reports/moomoo-live-quotes.json

OpenD defaults:
    MOOMOO_OPEND_HOST=127.0.0.1
    MOOMOO_OPEND_PORT=11111

Usage:
    python3 -m scripts.ingest.moomoo --tickers NVDA,MU,AMD
    python3 -m scripts.ingest.moomoo --full-universe
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pandas as pd
import yaml

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
UNI = ROOT / "config" / "universe.yaml"
PRICES = ROOT / "data" / "prices.duckdb"
OUT = ROOT / "data" / "intraday_snap.parquet"
REPORT = ROOT / "reports" / "moomoo-live-quotes.json"
ET = ZoneInfo("America/New_York")


def _load_moomoo():
    try:
        import moomoo as mm
        return mm
    except ModuleNotFoundError:
        try:
            import futu as mm
            return mm
        except ModuleNotFoundError as exc:
            raise SystemExit(
                "moomoo OpenAPI package is not installed. Run: "
                "./.venv-tb/bin/python -m pip install moomoo-api==10.6.6608"
            ) from exc


def _port_open(host: str, port: int, timeout_s: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def load_universe() -> list[str]:
    cfg = yaml.safe_load(UNI.read_text())
    tickers: list[str] = list(cfg.get("regime_benchmarks", []))
    for _, names in cfg.get("universe", {}).items():
        tickers.extend(names)
    seen, out = set(), []
    for t in tickers:
        if t not in seen and not str(t).endswith("-USD"):
            seen.add(t)
            out.append(str(t).upper())
    return out


def moomoo_code(ticker: str) -> str:
    t = ticker.strip().upper()
    if "." in t:
        return t
    return f"US.{t}"


def plain_ticker(code: str) -> str:
    return code.split(".", 1)[1] if "." in code else code


def prev_close_map(tickers: list[str]) -> dict[str, float]:
    try:
        con = duckdb.connect(str(PRICES), read_only=True)
        rows = con.execute("""
            SELECT ticker, close
            FROM prices p
            WHERE date = (SELECT MAX(date) FROM prices p2 WHERE p2.ticker = p.ticker)
              AND ticker = ANY(?)
        """, [tickers]).fetchall()
        con.close()
        return {str(t): float(c) for t, c in rows}
    except Exception as exc:
        print(f"  ! prev_close lookup failed: {exc}", file=sys.stderr)
        return {}


def infer_market_state(now_et: datetime) -> str:
    if now_et.weekday() >= 5:
        return "CLOSED"
    from datetime import time as dtime
    t = now_et.time()
    if dtime(4, 0) <= t < dtime(9, 30):
        return "PRE"
    if dtime(9, 30) <= t < dtime(16, 0):
        return "REGULAR"
    if dtime(16, 0) <= t < dtime(20, 0):
        return "POST"
    return "CLOSED"


def _num(row: pd.Series, name: str):
    if name not in row:
        return None
    val = row.get(name)
    if pd.isna(val):
        return None
    try:
        return float(val)
    except Exception:
        return None


def _ts(row: pd.Series, now_utc: datetime) -> datetime:
    raw = row.get("update_time") or row.get("data_time")
    if raw:
        try:
            return datetime.fromisoformat(str(raw)).replace(tzinfo=ET).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:
            pass
    return now_utc.replace(tzinfo=None)


def snapshot_to_frame(snapshot: pd.DataFrame, previous: dict[str, float], now_utc: datetime | None = None) -> pd.DataFrame:
    now = now_utc or datetime.now(timezone.utc)
    state = infer_market_state(now.astimezone(ET))
    rows = []
    for _, row in snapshot.iterrows():
        code = str(row.get("code", "")).upper()
        ticker = plain_ticker(code)
        last = _num(row, "last_price")
        if last is None or last <= 0:
            last = _num(row, "pre_price") or _num(row, "after_price")
        if last is None or last <= 0:
            continue
        prev = _num(row, "prev_close_price") or previous.get(ticker)
        bid = _num(row, "bid_price")
        ask = _num(row, "ask_price")
        update_ts = _ts(row, now)
        rows.append({
            "ticker": ticker,
            "last_price": float(last),
            "prev_close": prev,
            "change_pct": ((float(last) / prev - 1.0) * 100.0) if prev else None,
            "market_state": state,
            "ts_utc": update_ts,
            "fetched_at_utc": now.replace(tzinfo=None),
            "source": "moomoo:market_snapshot",
            "bid": bid,
            "ask": ask,
            "bid_vol": _num(row, "bid_vol"),
            "ask_vol": _num(row, "ask_vol"),
            "sec_status": str(row.get("sec_status")) if "sec_status" in row else None,
        })
    return pd.DataFrame(rows)


def fetch_snapshot(codes: list[str], host: str, port: int, batch_size: int = 400) -> pd.DataFrame:
    if not _port_open(host, port):
        raise SystemExit(
            f"moomoo OpenD is not reachable at {host}:{port}. Start moomoo OpenD, "
            "log in, and enable OpenAPI before running this ingest."
        )
    mm = _load_moomoo()
    quote_ctx = mm.OpenQuoteContext(host=host, port=port)
    frames = []
    try:
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            ret, data = quote_ctx.get_market_snapshot(batch)
            if ret != mm.RET_OK:
                raise SystemExit(f"moomoo snapshot failed for batch {i // batch_size + 1}: {data}")
            frames.append(data)
    finally:
        quote_ctx.close()
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def write_reports(df: pd.DataFrame, codes: list[str], host: str, port: int, elapsed: float) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, index=False)
    summary = {
        "asof": datetime.now(timezone.utc).isoformat(),
        "source": "moomoo:market_snapshot",
        "host": host,
        "port": port,
        "requested": len(codes),
        "returned": int(len(df)),
        "elapsed_seconds": round(elapsed, 3),
        "output": str(OUT),
        "sample": df.head(10).to_dict(orient="records"),
        "safety": {
            "market_data_only": True,
            "live_trading_enabled": False,
            "mode_required": "paper",
        },
    }
    REPORT.write_text(json.dumps(summary, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated symbols, e.g. NVDA,MU,AMD")
    ap.add_argument("--full-universe", action="store_true", help="snap the full configured universe")
    ap.add_argument("--host", default=os.environ.get("MOOMOO_OPEND_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("MOOMOO_OPEND_PORT", "11111")))
    args = ap.parse_args(argv)

    if os.environ.get("TB_MODE", "paper") == "live" or os.environ.get("TB_ALLOW_LIVE", "0") == "1":
        raise SystemExit("Refusing to run with live execution flags. Set TB_MODE=paper and TB_ALLOW_LIVE=0.")

    if args.full_universe or not args.tickers:
        tickers = load_universe()
    else:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    codes = [moomoo_code(t) for t in tickers]
    print(f"moomoo snapshot: {len(codes)} US symbols via OpenD {args.host}:{args.port}")

    t0 = time.time()
    raw = fetch_snapshot(codes, args.host, args.port)
    df = snapshot_to_frame(raw, prev_close_map([plain_ticker(c) for c in codes]))
    if df.empty:
        raise SystemExit("moomoo snapshot returned no usable rows")
    write_reports(df, codes, args.host, args.port, time.time() - t0)
    try:
        from monitoring import live_data_health
        live_data_health.write(host=args.host, port=args.port)
    except Exception as exc:
        print(f"  ! live-data health report failed: {exc}", file=sys.stderr)
    print(f"Wrote {len(df)} moomoo snaps -> {OUT}")
    print(df[["ticker", "last_price", "bid", "ask", "change_pct", "market_state"]].head(10).to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
