#!/usr/bin/env bash
echo "QUARANTINED: this wrapper had unsafe write powers. Use safety/operator.py + execution/order_manager.py."; exit 3
# Alpaca API wrapper. All trading API calls go through here.
# Usage: bash scripts/wrappers/alpaca.sh <subcommand> [args]
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
  order)      curl -fsS -H "$H_KEY" -H "$H_SEC" -H "Content-Type: application/json" -X POST -d "${1:?usage: order '<json>'}" "$API/orders" ;;
  cancel)     curl -fsS -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/orders/${1:?usage: cancel ORDER_ID}" ;;
  cancel-all) curl -fsS -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/orders" ;;
  close)      curl -fsS -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/positions/${1:?usage: close SYM}" ;;
  close-all)  curl -fsS -H "$H_KEY" -H "$H_SEC" -X DELETE "$API/positions" ;;
  *) echo "usage: alpaca.sh {account|positions|position SYM|quote SYM|orders [status]|order JSON|cancel ID|cancel-all|close SYM|close-all}"; exit 2 ;;
esac
