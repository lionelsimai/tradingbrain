#!/usr/bin/env bash
set -euo pipefail
cd /home/workspace/TradingBrain
python3 scripts/ingest.py >> reports/_pipeline.log 2>&1
python3 scripts/momentum.py >> reports/_pipeline.log 2>&1
python3 scripts/report.py
