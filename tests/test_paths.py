import os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import paths

def test_exposes_dirs():
    for a in ("ROOT","CONFIG_DIR","DATA_DIR","REPORTS_DIR","LOGS_DIR","DB_DIR","DOCS_DIR"):
        assert hasattr(paths, a)

def test_root_is_repo():
    assert (paths.ROOT / "config" / "risk_policy.yaml").exists()

def test_env_override(tmp_path):
    # TRADINGBRAIN_ROOT should win
    out = subprocess.run([sys.executable, str(ROOT/"paths.py")],
        env={**os.environ, "TRADINGBRAIN_ROOT": str(ROOT)}, capture_output=True, text=True)
    assert "ROOT" in out.stdout

def test_works_from_other_cwd():
    out = subprocess.run([sys.executable, "-c",
        f"import sys; sys.path.insert(0,'{ROOT}'); import paths; print(paths.CONFIG_DIR)"],
        cwd="/tmp", capture_output=True, text=True)
    assert "config" in out.stdout
