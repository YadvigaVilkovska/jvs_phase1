#!/usr/bin/env bash
# Manual smoke against a running Jeeves API. Requires curl and jq.
# Start the server first, e.g.:
#   export DATABASE_URL="sqlite:///./data/jeeves.db"
#   export JEEVES_DEV_STUB_AGENTS=true
#   uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
#
# Then: BASE=http://127.0.0.1:8000 bash scripts/smoke_test.sh

set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8000}"

echo "== GET /health"
curl -sf "${BASE}/health" | jq .

echo "== GET /dev/ping-db"
curl -sf "${BASE}/dev/ping-db" | jq .

echo "== POST /dev/bootstrap-chat"
curl -sf -X POST "${BASE}/dev/bootstrap-chat" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"smoke-user"}' | jq .

echo "== POST /dev/demo-flow (requires JEEVES_DEV_STUB_AGENTS=true on server for keyless run)"
curl -sf -X POST "${BASE}/dev/demo-flow" \
  -H "Content-Type: application/json" \
  -d '{"user_id":"smoke-user","user_message":"Hello, Jeeves."}' | jq .

echo "OK smoke finished."
