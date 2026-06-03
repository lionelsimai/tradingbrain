import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portfolio.portfolio_state import PortfolioState, Position
from portfolio import constraints

def test_empty_allows():
    s=PortfolioState(account_equity=50000,cash=50000,buying_power=50000)
    assert constraints.evaluate("NVDA","buy",5000,250,s)==[]

def test_duplicate_blocked():
    s=PortfolioState(account_equity=50000,cash=50000,buying_power=50000,
        positions=[Position("NVDA",10,200,210,195)])
    v=constraints.evaluate("NVDA","buy",5000,250,s)
    assert any("duplicate" in x for x in v)

def test_position_cap():
    s=PortfolioState(account_equity=50000,cash=50000,buying_power=50000)
    v=constraints.evaluate("NVDA","buy",20000,250,s)  # 40% > 10%
    assert any("position" in x for x in v)

def test_insufficient_cash():
    s=PortfolioState(account_equity=50000,cash=1000,buying_power=1000)
    v=constraints.evaluate("NVDA","buy",5000,250,s)
    assert any("cash" in x for x in v)

def test_max_concurrent():
    pos=[Position(f"S{i}",1,100,100,95) for i in range(6)]
    s=PortfolioState(account_equity=50000,cash=50000,buying_power=50000,positions=pos)
    v=constraints.evaluate("NEW","buy",1000,50,s)
    assert any("concurrent" in x for x in v)
