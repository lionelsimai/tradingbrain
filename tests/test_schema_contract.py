import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database import schema, contracts

def test_fresh_db_valid(tmp_path):
    p=tmp_path/"kb.duckdb"
    schema.init(p)
    assert schema.validate(p)["ok"]

def test_contracts_pass(tmp_path):
    p=tmp_path/"kb2.duckdb"
    schema.init(p)
    assert contracts.check(p)["ok"]
