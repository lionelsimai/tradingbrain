"""Sector/peer relative strength — isolate stock-specific edge from sector beta.

The base engine measures relative strength vs SPY (rs20). That conflates a stock's
own edge with its sector's tailwind: "NVDA beat SPY" says less than "NVDA beat its
semiconductor peers". This module computes peer-relative strength — a stock's
trailing return minus the *median* return of its sector peers — and converts it
into a small, bounded conviction adjustment.

Pure core (takes precomputed returns, fully testable) plus a best-effort DuckDB
loader. Degrades to a no-op when peer data is missing. No look-ahead: returns are
trailing.
"""
from __future__ import annotations

from pathlib import Path

# Bounded contribution so peer-RS confirms/tilts but never dominates the picture.
MAX_POINTS = 6.0


def sector_map_from_universe(universe: dict) -> dict:
    """Flatten config/universe.yaml {universe: {sector: [tickers]}} -> {ticker: sector}."""
    out: dict[str, str] = {}
    for sector, tickers in (universe or {}).get("universe", {}).items():
        for t in (tickers or []):
            out[str(t).upper()] = sector
    return out


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def peer_relative_strength(returns: dict, ticker: str, sector_map: dict,
                           min_peers: int = 3) -> dict | None:
    """ticker's trailing return minus its sector peers' median return.

    returns: {TICKER: trailing_return_fraction}. Returns None if there is not
    enough peer data to be meaningful (then the caller treats it as no signal).
    """
    ticker = str(ticker).upper()
    if ticker not in returns:
        return None
    sector = sector_map.get(ticker)
    if not sector:
        return None
    peers = [t for t, s in sector_map.items()
             if s == sector and t != ticker and t in returns]
    if len(peers) < min_peers:
        return None
    peer_med = _median([returns[t] for t in peers])
    rs = returns[ticker] - peer_med
    # rank within the sector (0..1), higher = stronger vs peers
    cohort = [returns[t] for t in peers] + [returns[ticker]]
    rank = sum(1 for v in cohort if v <= returns[ticker]) / len(cohort)
    return {
        "rs_vs_peers": round(rs, 4),
        "sector": sector,
        "peer_n": len(peers),
        "peer_median_return": round(peer_med, 4),
        "sector_rank": round(rank, 3),
    }


def conviction_points(prs: dict | None) -> float:
    """Map a peer-RS read to a bounded conviction adjustment in [-MAX, +MAX]."""
    if not prs:
        return 0.0
    # 10 percentage points of peer outperformance ~ full bonus.
    pts = (prs["rs_vs_peers"] / 0.10) * MAX_POINTS
    return float(max(-MAX_POINTS, min(MAX_POINTS, pts)))


def compute_peer_rs(prices_db: Path, tickers: list[str], sector_map: dict,
                    lookback: int = 20) -> dict:
    """Best-effort: pull trailing `lookback`-day returns from prices.duckdb and
    compute peer-RS for each ticker. Returns {TICKER: read}. Empty on any error
    (the overlay then simply omits the peer-RS adjustment)."""
    try:
        import duckdb  # noqa: WPS433
    except Exception:
        return {}
    out: dict[str, dict] = {}
    try:
        con = duckdb.connect(str(prices_db), read_only=True)
    except Exception:
        return {}
    try:
        universe = sorted({str(t).upper() for t in sector_map})
        rows = con.execute(
            "SELECT ticker, date, close FROM prices "
            "WHERE ticker IN ({}) ORDER BY ticker, date".format(
                ",".join("?" for _ in universe)),
            universe,
        ).fetchall()
    except Exception:
        con.close()
        return {}
    con.close()

    by_ticker: dict[str, list[float]] = {}
    for tkr, _dt, close in rows:
        by_ticker.setdefault(str(tkr).upper(), []).append(float(close))
    returns: dict[str, float] = {}
    for tkr, closes in by_ticker.items():
        if len(closes) > lookback and closes[-lookback - 1] > 0:
            returns[tkr] = closes[-1] / closes[-lookback - 1] - 1.0
    for t in tickers:
        prs = peer_relative_strength(returns, t, sector_map)
        if prs:
            out[str(t).upper()] = prs
    return out
