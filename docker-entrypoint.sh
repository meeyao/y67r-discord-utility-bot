#!/bin/sh
set -eu

cd /app/vendor/unofficial-urban-dictionary-api
node src/server.js &
urban_pid=$!

cd /app/ppv-resolver
node src/server.js &
ppv_pid=$!

cleanup() {
  kill "$bot_pid" 2>/dev/null || true
  kill "$urban_pid" 2>/dev/null || true
  kill "$ppv_pid" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

cd /app
python -m convertcord.bot &
bot_pid=$!
wait "$bot_pid"
