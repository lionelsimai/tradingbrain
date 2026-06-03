"""FIX-8 (P1-3): a bare OrderManager() must default to PAPER and must NOT inherit
"live" from the TB_MODE env var (defense-in-depth — it shouldn't take a downstream
gate to stop an env-inherited live order)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import order_manager as om


def test_bare_manager_defaults_to_paper_not_env_live(monkeypatch):
    monkeypatch.setenv("TB_MODE", "live")      # hostile / leftover env
    monkeypatch.setenv("TB_ALLOW_LIVE", "1")
    assert om.OrderManager().mode == "paper", "bare OrderManager inherited live from env"


def test_explicit_mode_still_respected():
    assert om.OrderManager(mode="backtest").mode == "backtest"
    assert om.OrderManager(mode="paper").mode == "paper"
