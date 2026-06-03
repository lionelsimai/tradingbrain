#!/usr/bin/env bash
# Cloud-environment provisioning for TradingBrain.
# IMPORTANT: the repo's requirements.txt pins versions that DON'T EXIST on PyPI
# (e.g. pandas==3.0.3 needs Python>=3.11 and isn't published; max is 2.3.x).
# This installs the validated, installable set on Python 3.11 instead.
set -e
echo "== TradingBrain cloud setup (Python $(python3 --version)) =="

python3 -m venv .venv
. .venv/bin/activate
pip install -q --upgrade pip
pip install -q -r requirements-cloud.txt

echo "✅ Python deps installed into .venv (the reconstructed data/ package is in-repo)."

# Web app (Next.js) deps — optional
if [ -d app ]; then
  ( cd app && npm install --silent ) && echo "✅ app/ npm deps installed" || echo "⚠️  app npm install skipped/failed (fine for backend work)"
fi

echo ""
echo "Next steps inside the env:"
echo "  . .venv/bin/activate"
echo "  python -m pytest -q                 # ~329 pass"
echo "  python -m safety.config_guard       # paper/safe"
echo "  python -m lab.go_live --json        # verdict: BLOCKED (correct)"
echo ""
echo "NOTE: 28 backtest/validation tests need the runtime *.duckdb knowledge base,"
echo "      which is NOT in the repo (market data). Everything else runs green."
