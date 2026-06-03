#!/usr/bin/env python3
"""Correlation clustering. 'Six positions' in a hyper-correlated AI basket is
really ~one big factor bet. This estimates correlated exposure so the portfolio
engine can cap it.

Uses cached daily-return correlations from the price DB when available; falls
back to the universe category map (same category => assumed correlated).
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import DATA_DIR, CONFIG_DIR

_CORR_CACHE: dict | None = None


def _category_map() -> dict:
    import yaml
    f = CONFIG_DIR / "universe.yaml"
    out = {}
    if f.exists():
        u = yaml.safe_load(f.read_text()) or {}
        for cat, items in (u.get("universe", u) or {}).items():
            if isinstance(items, list):
                for t in items:
                    out[str(t)] = cat
    return out


def pairwise_corr(a: str, b: str, lookback_days: int = 252) -> float:
    """Daily-return correlation a vs b; 1.0 if same symbol, category fallback."""
    if a == b:
        return 1.0
    global _CORR_CACHE
    db = DATA_DIR / "prices.duckdb"
    if db.exists():
        try:
            import duckdb
            con = duckdb.connect(str(db), read_only=True)
            df = con.execute(
                "SELECT date, ticker, close FROM prices WHERE ticker IN (?,?) "
                "AND date > (SELECT MAX(date) FROM prices) - INTERVAL (?) DAY",
                [a, b, lookback_days * 2]).fetchdf()
            con.close()
            piv = df.pivot(index="date", columns="ticker", values="close").pct_change().dropna()
            if a in piv and b in piv and len(piv) > 20:
                return float(piv[a].corr(piv[b]))
        except Exception:
            pass
    cm = _category_map()
    return 0.7 if cm.get(a) and cm.get(a) == cm.get(b) else 0.0


def correlated_exposure_pct(symbol: str, state, threshold: float = 0.6) -> float:
    """Sum of notional %% of existing positions correlated with `symbol` above
    threshold (plus the symbol's own category peers)."""
    total = 0.0
    for p in state.positions:
        if abs(pairwise_corr(symbol, p.symbol)) >= threshold:
            total += p.notional
    if state.account_equity <= 0:
        return 0.0
    return total / state.account_equity * 100


if __name__ == "__main__":
    print("NVDA~AMD", round(pairwise_corr("NVDA", "AMD"), 3))
    print("NVDA~NVDA", pairwise_corr("NVDA", "NVDA"))
