import importlib
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def test_core_deps_importable():
    for m in ("duckdb","pandas","numpy","yaml","pyarrow"):
        importlib.import_module(m)

def test_requirements_pinned():
    req = (ROOT/"requirements.txt").read_text()
    assert "duckdb" in req and "==" in req

def test_constraints_exist():
    assert (ROOT/"constraints.txt").exists()
