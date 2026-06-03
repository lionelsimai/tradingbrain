#!/usr/bin/env python3
"""Reproducibility & provenance. A 10/10 instrument can answer 'which exact code
and data produced this number?' for every report.

Hashes the price/knowledge databases and all source code, captures library
versions and the global seed, and writes reports/MANIFEST.json. Re-running the
pipeline on unchanged inputs must reproduce the same hashes and headline results.
"""
from __future__ import annotations
import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = next((p for p in Path(__file__).resolve().parents if (p / "DOCTRINE.md").exists() and (p / "config").is_dir()), Path(__file__).resolve().parent)
REPORTS = ROOT / "reports"
GLOBAL_SEED = 7


def _sha256(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def code_hash() -> dict:
    """Hash every tracked .py / .yaml / doctrine file (sorted, deterministic)."""
    files = []
    for pat in ("scripts/**/*.py", "backtest/**/*.py", "loops/**/*.py",
                "lab/**/*.py", "config/*.yaml", "DOCTRINE.md"):
        files.extend(ROOT.glob(pat))
    files = sorted(set(p for p in files if p.is_file() and "__pycache__" not in str(p)))
    h = hashlib.sha256()
    per = {}
    for p in files:
        d = _sha256(p)
        per[str(p.relative_to(ROOT))] = d[:12]
        h.update(d.encode())
    return {"combined": h.hexdigest()[:16], "n_files": len(files), "files": per}


def data_hash() -> dict:
    out = {}
    for name in ("prices.duckdb", "knowledge.duckdb"):
        p = ROOT / "data" / name
        out[name] = (_sha256(p)[:16] if p.exists() else None)
    return out


def _headline() -> dict:
    """Pull the key numbers from the freshly-written reports for the manifest."""
    res = {}
    def load(name):
        p = REPORTS / name
        return json.loads(p.read_text()) if p.exists() else {}
    cal = load("calibration.json").get("calibration", {})
    res["calibration_expectancy_R"] = {k: v.get("expectancy_R") for k, v in cal.items()}
    sc = load("live-scorecard.json")
    res["scorecard_verdict"] = sc.get("verdict")
    rr = load("research-report.json").get("strategies", {})
    res["research_decisions"] = {k: (v.get("verdict") if isinstance(v.get("verdict"), str)
                                     else v.get("verdict", {}).get("decision"))
                                 for k, v in rr.items()}
    res["pbo"] = load("research-report.json").get("portfolio_pbo")
    return res


def write_manifest(extra: dict | None = None) -> Path:
    man = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "global_seed": GLOBAL_SEED,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "libs": {},
        "data_hash": data_hash(),
        "code_hash": code_hash(),
        "headline_results": _headline(),
    }
    for lib in ("numpy", "pandas", "duckdb"):
        try:
            man["libs"][lib] = __import__(lib).__version__
        except Exception:
            man["libs"][lib] = None
    if extra:
        man.update(extra)
    out = REPORTS / "MANIFEST.json"
    out.write_text(json.dumps(man, indent=2, default=str))
    return out


if __name__ == "__main__":
    p = write_manifest()
    m = json.loads(p.read_text())
    print(f"Wrote {p}")
    print(f"  code hash {m['code_hash']['combined']} ({m['code_hash']['n_files']} files)")
    print(f"  data hash {m['data_hash']}")
    print(f"  seed {m['global_seed']} · numpy {m['libs']['numpy']} · pandas {m['libs']['pandas']}")
