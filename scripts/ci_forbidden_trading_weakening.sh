#!/usr/bin/env bash
# CI guard (red-team §20): FAIL if any forbidden trading-safety WEAKENING appears
# in real source/config. It only DETECTS regressions — it never weakens anything.
#
# Design note: YAML-form weakenings (`key: true/false`) are scanned in *.yaml ONLY
# (the canonical risk config). In .py those exact strings appear only inside
# detection-lists / docstrings (e.g. loops/harden_live_readiness.py FORBIDDEN_PATCHES,
# which is itself a guard) — scanning them there causes false positives. Python-level
# weakenings are matched by the assignment/flag forms below.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2

SCAN_DIRS="safety execution portfolio lab backtest scripts loops ops config data brain strategies agents"
hits=0

check() {  # $1=regex  $2=description  $3..=grep --include args
  local rx="$1" desc="$2"; shift 2
  local out
  out=$(grep -rniE "$rx" $SCAN_DIRS "$@" 2>/dev/null \
        | grep -vE '/(tests?|deprecated)/' \
        | grep -v 'ci_forbidden_trading_weakening')
  if [ -n "$out" ]; then
    echo "FORBIDDEN — ${desc}:"; echo "$out"; hits=$((hits + 1))
  fi
}

# --- YAML config weakenings: scan real config only ---
Y=(--include='*.yaml' --include='*.yml')
check 'live_trading_enabled:[[:space:]]*true'                'live trading enabled'             "${Y[@]}"
check 'paper_only:[[:space:]]*false'                         'paper-only disabled'              "${Y[@]}"
check 'require_human_approval_for_live:[[:space:]]*false'    'live human-approval disabled'     "${Y[@]}"
check 'require_explicit_live_flag:[[:space:]]*false'         'explicit-live-flag disabled'      "${Y[@]}"
check 'require_stop_loss:[[:space:]]*false'                  'stop-loss requirement disabled'   "${Y[@]}"
check 'require_target_or_trailing_policy:[[:space:]]*false'  'exit-policy requirement disabled' "${Y[@]}"
check 'allow_market_orders:[[:space:]]*true'                 'market orders enabled'            "${Y[@]}"
check 'fail_closed_on_unknown:[[:space:]]*false'             'fail-closed disabled'             "${Y[@]}"
check 'replay_not_allowed_for_live_gate:[[:space:]]*false'   'replay allowed into live gate'    "${Y[@]}"
check 'paper_not_allowed_for_live_gate:[[:space:]]*false'    'paper allowed into live gate'     "${Y[@]}"

# --- Python/flag weakenings: scan source + config ---
B=(--include='*.py' --include='*.yaml' --include='*.yml')
check 'live_trading_enabled[[:space:]]*=[[:space:]]*True'    'live flag set in code'            "${B[@]}"
check 'require_stop_loss[[:space:]]*=[[:space:]]*False'      'stop-loss disabled in code'       "${B[@]}"
check '(LIVE_READY|LIVE_ENABLED|PRODUCTION_TRADING_ENABLED)[[:space:]]*=[[:space:]]*(true|1|True)' \
                                                            'live-ready flag set'              "${B[@]}"

if [ "$hits" -gt 0 ]; then
  echo "ci_forbidden_trading_weakening: ${hits} forbidden pattern(s) found — FAIL"; exit 1
fi
echo "ci_forbidden_trading_weakening: clean"; exit 0
