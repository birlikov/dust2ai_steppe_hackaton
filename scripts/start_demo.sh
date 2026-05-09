#!/usr/bin/env bash
# Bring up the storefront + backend on a single ngrok URL.
#
#   1. Build the Astro storefront with relative API URLs
#      (PUBLIC_API_BASE="" → chat widget posts back to the same origin).
#   2. Start FastAPI on :8000. The app mounts web/dist/ as a static
#      catch-all under /, so the same port serves the API and the site.
#   3. Open an ngrok tunnel on :8000 and echo the public URL.
#
# Press Ctrl-C to stop; both background processes are killed via trap.
#
# Requires: claude on PATH, .env with TELEGRAM_BOT_TOKEN + SBC_TEAM_TOKEN,
# ngrok with NGROK_AUTHTOKEN configured (or in `.env`), node + npm.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data

echo "▶ building web/ (PUBLIC_API_BASE='' for relative URLs)…"
(
    cd web
    if [ ! -d node_modules ]; then
        npm install --silent
    fi
    PUBLIC_API_BASE= npm run build > "$REPO_ROOT/data/web-build.log" 2>&1
)
echo "  build → web/dist/"

echo "▶ starting uvicorn on :8000…"
uv run uvicorn src.webhooks.app:app --host 127.0.0.1 --port 8000 \
    > data/uvicorn.log 2>&1 &
UVICORN_PID=$!

cleanup() {
    echo
    echo "▶ stopping…"
    kill "$UVICORN_PID" 2>/dev/null || true
    pkill -f "ngrok http 8000" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# Wait for /health
echo -n "  waiting for /health"
for _ in $(seq 1 30); do
    if curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 0.5
done

if ! curl -fsS http://127.0.0.1:8000/health > /dev/null 2>&1; then
    echo " ✗ uvicorn failed to start — see data/uvicorn.log" >&2
    exit 1
fi

echo "▶ starting ngrok on :8000…"
ngrok http 8000 --log=stdout > data/ngrok.log 2>&1 &

# Wait for ngrok local API to come up
echo -n "  waiting for ngrok"
for _ in $(seq 1 20); do
    if curl -fsS http://127.0.0.1:4040/api/tunnels > /dev/null 2>&1; then
        echo " ✓"
        break
    fi
    echo -n "."
    sleep 0.5
done

# Read the public URL via ngrok's local API. Retry briefly — the tunnel
# may not be fully up the instant the local API responds.
PUBLIC_URL=""
for _ in $(seq 1 20); do
    body=$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null || true)
    if [ -n "$body" ]; then
        PUBLIC_URL=$(printf '%s' "$body" | python3 - <<'PY' 2>/dev/null || true
import json, sys
try:
    tunnels = json.load(sys.stdin).get("tunnels") or []
except json.JSONDecodeError:
    tunnels = []
for t in tunnels:
    if t.get("proto") == "https" and t.get("public_url"):
        print(t["public_url"])
        break
PY
)
    fi
    if [ -n "$PUBLIC_URL" ]; then
        break
    fi
    sleep 0.5
done

if [ -z "$PUBLIC_URL" ]; then
    echo "✗ couldn't read ngrok public URL — see data/ngrok.log" >&2
    cat data/ngrok.log >&2 || true
    exit 1
fi

cat <<EOF

✓ Public URL:      $PUBLIC_URL

  Storefront:      $PUBLIC_URL
  Catalog JSON:    $PUBLIC_URL/api/catalog
  Policies JSON:   $PUBLIC_URL/api/policies
  OpenAPI:         $PUBLIC_URL/openapi.json
  agent.txt:       $PUBLIC_URL/agent.txt

  Tap the chat widget on the homepage — it posts to ${PUBLIC_URL}/api/chat
  on the same origin (no CORS, no separate port).

  Press Ctrl-C to stop both processes.
EOF

# Block until the user stops; trap will tear down both processes.
wait $UVICORN_PID
