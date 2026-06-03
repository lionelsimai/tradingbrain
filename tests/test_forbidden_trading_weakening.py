"""CI guard test (red-team §20): the forbidden-trading-weakening scanner must
(a) pass on the clean tree and (b) catch a planted weakening.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "ci_forbidden_trading_weakening.sh"


def _run():
    return subprocess.run(["bash", str(SCANNER)], capture_output=True, text=True)


def test_scanner_passes_on_clean_tree():
    r = _run()
    assert r.returncode == 0, f"scanner should be clean but failed:\n{r.stdout}\n{r.stderr}"


def test_scanner_catches_planted_live_flag(tmp_path):
    planted = ROOT / "config" / "_redteam_planted.yaml"
    planted.write_text("live_trading_enabled: true\n")
    try:
        r = _run()
        assert r.returncode == 1, "scanner must FAIL when a live flag is planted"
        assert "live_trading_enabled" in r.stdout.lower() or "forbidden" in r.stdout.lower()
    finally:
        planted.unlink(missing_ok=True)


def test_scanner_catches_planted_stop_weakening(tmp_path):
    planted = ROOT / "config" / "_redteam_planted2.yaml"
    planted.write_text("require_stop_loss: false\n")
    try:
        r = _run()
        assert r.returncode == 1, "scanner must FAIL when stop-loss requirement is disabled"
    finally:
        planted.unlink(missing_ok=True)
