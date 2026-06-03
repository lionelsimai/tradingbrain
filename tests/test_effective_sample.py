import sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scorecards import effective_sample as es

def test_overlap_reduces_n():
    a=es.analyze(np.random.default_rng(1).normal(0,1,500),avg_hold_bars=8,step_bars=3)
    assert a["effective_n_formula"] < a["raw_n"]
    assert any("overlap" in w for w in a["warnings"])

def test_formula():
    assert es.effective_n(100, 8, 4) == 50
