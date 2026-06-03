"""FIX-3: prove transaction costs are wired into backtest/engine.py and actually
reduce returns. DB-free — monkeypatches load_prices with synthetic data so it runs
without the price *.duckdb knowledge base.
"""
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import engine


def _synth():
    # ~160 business days of steadily-rising prices, 3 tickers in DIFFERENT
    # universe categories (so the sector cap doesn't block entries).
    idx = pd.bdate_range("2024-01-01", periods=160).date
    cols = {"NVDA": 100.0, "MU": 80.0, "CRWD": 200.0}   # gpu / memory / cyber
    data = {c: [base * (1.004 ** i) for i in range(len(idx))] for c, base in cols.items()}
    return pd.DataFrame(data, index=pd.Index(idx, name="date"))


SYNTH = _synth()


def test_engine_imports_and_uses_cost_model():
    assert hasattr(engine, "COST_MODEL")
    assert engine.COST_MODEL.round_trip_bps() > 0       # not the old zero-cost engine
    assert engine._PS > 0


def test_costs_reduce_final_equity(monkeypatch):
    monkeypatch.setattr(engine, "load_prices", lambda s, e, t=None: SYNTH)
    start, end = SYNTH.index[100], SYNTH.index[-1]

    monkeypatch.setattr(engine, "_PS", 0.0)             # costless (diagnosis)
    free = engine.run_backtest(start, end, regime_filter=False, tickers=list(SYNTH.columns))

    monkeypatch.setattr(engine, "_PS", 0.002)           # 20 bps / side
    cost = engine.run_backtest(start, end, regime_filter=False, tickers=list(SYNTH.columns))

    # Entries must have happened, and costs must eat into the result.
    assert cost.final_equity < free.final_equity, (cost.final_equity, free.final_equity)
