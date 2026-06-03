import sys
from pathlib import Path
import pandas as pd
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from data import data_contract as dc

def _good():
    return pd.DataFrame({"date": pd.date_range("2024-01-01", periods=5),
        "open":[10,11,12,11,13],"high":[11,12,13,12,14],"low":[9,10,11,10,12],
        "close":[10.5,11.5,12.5,11.5,13.5],"volume":[100,200,150,180,220]})

def test_good_frame():
    assert dc.validate_frame(_good())["ok"]

def test_negative_price_fails():
    d=_good(); d.loc[2,"close"]=-1
    assert not dc.validate_frame(d)["ok"]

def test_inversion_fails():
    d=_good(); d.loc[2,"high"]=1
    assert not dc.validate_frame(d)["ok"]

def test_missing_column_fails():
    d=_good().drop(columns=["volume"])
    assert not dc.validate_frame(d)["ok"]
