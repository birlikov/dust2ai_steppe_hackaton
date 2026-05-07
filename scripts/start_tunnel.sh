#!/usr/bin/env bash
# Start the FastAPI webhook receiver behind an ngrok tunnel.
#
# Requirements:
#   - ngrok installed and authenticated (NGROK_AUTHTOKEN in .env)
#   - Optional: NGROK_DOMAIN for a stable URL across restarts
#
# Usage:
#   ./scripts/start_tunnel.sh           # default port 8000
#   ./scripts/start_tunnel.sh 8080      # custom port
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

PORT="${1:-8000}"

# Load .env if present (for NGROK_AUTHTOKEN, NGROK_DOMAIN)
if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  . .env
  set +a
fi

if ! command -v ngrok >/dev/null 2>&1; then
  echo "ngrok not found. Install: https://ngrok.com/download" >&2
  exit 1
fi

if [[ -n "${NGROK_AUTHTOKEN:-}" ]]; then
  ngrok config add-authtoken "$NGROK_AUTHTOKEN" >/dev/null
fi

# Run uvicorn in the background, ngrok in the foreground.
uv run uvicorn src.webhooks.app:app --port "$PORT" --log-level warning &
UVICORN_PID=$!
trap 'kill $UVICORN_PID 2>/dev/null || true' EXIT

# Give uvicorn a beat to bind before ngrok latches on.
sleep 1

NGROK_ARGS=(http "$PORT" --log=stdout)
if [[ -n "${NGROK_DOMAIN:-}" ]]; then
  NGROK_ARGS+=(--domain="$NGROK_DOMAIN")
fi

echo "→ Webhook server on http://127.0.0.1:$PORT (PID $UVICORN_PID)"
echo "→ Starting ngrok…"
ngrok "${NGROK_ARGS[@]}"
