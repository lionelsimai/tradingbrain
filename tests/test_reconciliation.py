import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution import reconciliation as rec

def test_ghost_is_incident():
    r=rec.reconcile([{"symbol":"NVDA","qty":10,"stop":9}],
                    [{"symbol":"NVDA","qty":10},{"symbol":"AMD","qty":5}])
    assert r.is_incident and r.blocks_entries

def test_quantity_mismatch_blocks():
    r=rec.reconcile([{"symbol":"NVDA","qty":10,"stop":9}],
                    [{"symbol":"NVDA","qty":15}])
    assert r.blocks_entries

def test_clean_ok():
    r=rec.reconcile([{"symbol":"NVDA","qty":10,"stop":9}],
                    [{"symbol":"NVDA","qty":10}])
    assert r.ok
