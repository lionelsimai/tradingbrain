import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_forbidden_live_weakening_scan_passes():
    r = subprocess.run(["bash", "scripts/ci_forbidden_live_weakening.sh"],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
