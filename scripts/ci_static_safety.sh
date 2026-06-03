#!/usr/bin/env bash
# CI static guard: fail the build on any unsafe pattern. Zero tolerance.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
fail=0
flag(){ echo "UNSAFE: $1"; fail=1; }

# 1. live order/cancel/close write calls in production (exclude tests + deprecated)
if grep -rEn -- "-X[[:space:]]+(POST|DELETE).*(/v2/orders|/v2/positions)" \
   --include=*.py --include=*.sh safety execution journal data scripts loops backtest 2>/dev/null \
   | grep -v "deprecated/"; then flag "raw broker write call in production"; fi

# 2. active alpaca.sh must be read-only
if grep -Eq -- "-X[[:space:]]+(POST|DELETE)" scripts/wrappers/alpaca.sh; then flag "active alpaca.sh has write verbs"; fi

# 3. hardcoded repo root in safety core
if grep -rqn "/home/workspace/TradingBrain" --include=*.py safety execution journal data paths.py; then flag "hardcoded root in safety core"; fi

# 4. hardcoded paper constants
if grep -rqn "START_EQUITY[[:space:]]*=[[:space:]]*100" --include=*.py scripts; then flag "hardcoded START_EQUITY"; fi

# 5. calibration reading combined scorecard for gating
if grep -rqn "scorecard-combined" --include=*.py scripts/calibration.py; then flag "calibration reads combined scorecard"; fi

# 6. agents importing broker/order_manager
if grep -rqn "broker_base\|order_manager\|alpaca" --include=*.py scripts/agents 2>/dev/null; then flag "agent imports execution/broker"; fi

# 7. agents/ or strategies/ packages importing execution/broker adapters
if grep -rEn "import (execution\.broker_base|execution\.order_manager|execution\.paper_adapter|scripts\.broker_alpaca)" \
   --include=*.py agents strategies 2>/dev/null; then flag "agent/strategy imports execution/broker"; fi

# 8. hardcoded root anywhere in the safety-critical core packages
if grep -rqn "/home/workspace/TradingBrain" --include=*.py \
   database portfolio scorecards agents strategies monitoring ops 2>/dev/null; then flag "hardcoded root in core package"; fi

# 9. calibration must not gate from replay/paper as if live
if grep -rqn "scorecard-paper.*live_gate\|may_drive_live_gate.*replay" --include=*.py scripts 2>/dev/null; then flag "replay/paper drives live gate"; fi

[ "$fail" = 0 ] && echo "static safety search: PASS"
exit $fail
