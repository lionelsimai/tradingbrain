#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
flag(){ echo "FORBIDDEN LIVE WEAKENING: $*" >&2; fail=1; }

grep -RIn --exclude-dir=.git --exclude-dir=.venv-tb --exclude-dir=node_modules \
  --include='*.yaml' --include='*.yml' --include='*.json' --include='*.py' --include='*.sh' \
  -E 'live_trading_enabled:[[:space:]]*true|require_human_approval_for_live:[[:space:]]*false|require_stop_loss:[[:space:]]*false|allow_market_orders:[[:space:]]*true|replay_not_allowed_for_live_gate:[[:space:]]*false|paper_not_allowed_for_live_gate:[[:space:]]*false' config \
  && flag "forbidden config literal found" || true

grep -RIn --include='*.py' --exclude-dir=.venv-tb \
  -E 'gate_reason_for_live|config_guard\.safe_to_trade|kill_switch\.blocked|risk_gate\.check' execution safety scripts lab >/tmp/tb_required_refs.$$ || true

grep -q 'gate_reason_for_live' /tmp/tb_required_refs.$$ || flag "go-live enforcement reference missing"
grep -q 'config_guard\.safe_to_trade' /tmp/tb_required_refs.$$ || flag "config guard enforcement reference missing"
grep -q 'risk_gate\.check' /tmp/tb_required_refs.$$ || flag "risk gate enforcement reference missing"
grep -q 'kill_switch\.blocked' /tmp/tb_required_refs.$$ || flag "kill switch enforcement reference missing"
rm -f /tmp/tb_required_refs.$$

if grep -RIn --include='*.py' --exclude-dir=.venv-tb \
  -E 'scorecard-replay.*gate5|scorecard-replay.*paper|paper.*scorecard-replay' lab scripts safety; then
  flag "replay scorecard appears to satisfy paper/live gate"
fi

if [[ "$fail" -ne 0 ]]; then
  exit 1
fi
echo "forbidden live weakening scan: PASS"
