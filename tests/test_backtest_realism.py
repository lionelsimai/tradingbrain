import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backtest import realism

def test_manifest_declares_limitations():
    m=realism.realism_manifest()
    assert m["survivorship_bias_free"] is False
    assert m["point_in_time_universe"] is False
    assert "INDICATIVE" in m["trust_level"]

def test_required_benchmarks_present():
    m=realism.realism_manifest()
    assert m["benchmark_QQQ"] and m["benchmark_equal_weight_universe"]

def test_cost_stress_reduces_edge():
    R=np.full(500, 0.05)
    cs=realism.cost_stress(R)
    assert cs["4x_36bps"] < cs["base_9bps"]
