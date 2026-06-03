#!/usr/bin/env bash
# Telegram notification wrapper (replaces ClickUp from the original spec).
# Usage: bash scripts/wrappers/telegram.sh "<markdown message>"
# Reads TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, else falls back to local log.
set -euo pipefail

MSG="${1:?usage: telegram.sh '<message>'}"
LOG="/home/workspace/TradingBrain/memory/notification-fallback.log"

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
  printf '[%s] %s\n\n' "$(date -Iseconds)" "$MSG" >> "$LOG"
  echo "fallback: appended to $LOG"
  exit 0
fi

curl -fsS -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
  -d "chat_id=${TELEGRAM_CHAT_ID}" \
  -d "parse_mode=Markdown" \
  --data-urlencode "text=${MSG}"
