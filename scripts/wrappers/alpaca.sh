#!/usr/bin/env bash
# Alpaca API wrapper — READ-ONLY. All WRITE actions (order/cancel/close) were
# removed: orders must flow through execution/order_manager.py, never a shell.
# Reads ALPACA_API_KEY + ALPACA_SECRET_KEY from environment.
set -euo pipefail

: "${ALPACA_API_KEY:?ALPACA_API_KEY not set in environment}"
: "${ALPACA_SECRET_KEY:?ALPACA_SECRET_KEY not set in environment}"

API="${ALPACA_ENDPOINT:-https://paper-api.alpaca.markets/v2}"
DATA="${ALPACA_DATA_ENDPOINT:-https://data.alpaca.markets/v2}"
H_KEY="APCA-API-KEY-ID: $ALPACA_API_KEY"
H_SEC="APCA-API-SECRET-KEY: $ALPACA_SECRET_KEY"

cmd="${1:-}"; shift || true
case "$cmd" in
  account)    curl -fsS -H "$H_KEY" -H "$H_SEC" "$API/account" ;;
  positions)  curl -fsS -H "$H_KEY" -H "$H_SEC" "$API/positions" ;;
  position)   curl -fsS -H "$H_KEY" -H "$H_SEC" "$API/positions/${1:?usage: position SYM}" ;;
  quote)      curl -fsS -H "$H_KEY" -H "$H_SEC" "$DATA/stocks/${1:?usage: quote SYM}/quotes/latest" ;;
  orders)     curl -fsS -H "$H_KEY" -H "$H_SEC" "$API/orders?status=${1:-open}&limit=100" ;;
  clock)      curl -fsS -H "$H_KEY" -H "$H_SEC" "$API/clock" ;;
  order|cancel|cancel-all|close|close-all)
    echo "REFUSED: '$cmd' is a WRITE action. Orders flow ONLY through execution/order_manager.py."
    echo "Use: python3 -m safety.operator <command>   (paper) — never a shell wrapper."
    exit 3 ;;
  *) echo "usage: alpaca.sh {account|positions|position SYM|quote SYM|orders [status]|clock}  (READ-ONLY)"; exit 2 ;;
esac
