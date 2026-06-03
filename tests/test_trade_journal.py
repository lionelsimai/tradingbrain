import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from safety import trade_journal as tj

def test_log_and_reconstruct():
    cid="test_recon_1"
    tj.log("order_proposed", cid, {"symbol":"NVDA"})
    tj.log("order_rejected", cid, {"reason":"x"})
    chain=tj.reconstruct(cid)
    types=[e["event"] for e in chain]
    assert "order_proposed" in types and "order_rejected" in types
