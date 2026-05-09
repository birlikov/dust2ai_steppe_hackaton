#!/usr/bin/env bash
# One-shot bootstrap: configure → build → launch everything → print public URL.
#
# What this script does, in order:
#   1. Validates .env has the two required tokens (TELEGRAM_BOT_TOKEN,
#      SBC_TEAM_TOKEN). Bails out with a clear message if either is missing.
#   2. Regenerates .mcp.json from .env so Claude Code's runtime persona
#      (claude -p subprocess) sees the happycake MCP server. The file is
#      gitignored — never edited by hand.
#   3. Idempotently ensures .claude/settings.local.json's permissions.allow
#      list includes "mcp__happycake__*" so the runtime can call MCP tools
#      without prompting in headless mode.
#   4. Installs Python deps (uv sync) and JS deps (npm install in web/).
#   5. Builds the Astro storefront with PUBLIC_API_BASE="" so it posts
#      back to the same origin.
#   6. Starts the FastAPI backend on :8000 (storefront mounted at /).
#   7. Starts the Telegram bot (--no-bot disables this).
#   8. Opens an ngrok tunnel on :8000 and prints the public HTTPS URL.
#
# Press Ctrl-C to stop everything. The trap kills all background processes.
#
# Usage:
#   ./scripts/run.sh            # full demo (bot + storefront + ngrok)
#   ./scripts/run.sh --no-bot   # storefront + ngrok only (skip Telegram)
#   ./scripts/run.sh --no-ngrok # local development on :8000

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

WITH_BOT=1
WITH_NGROK=1
for arg in "$@"; do
    case "$arg" in
        --no-bot) WITH_BOT=0 ;;
        --no-ngrok) WITH_NGROK=0 ;;
        --help|-h)
            head -25 "$0" | sed -n 's/^# \?//p'
            exit 0
            ;;
        *)
            echo "Unknown flag: $arg" >&2
            exit 2
            ;;
    esac
done

mkdir -p data

# ---------------------------------------------------------------------------
# 1. Validate .env
# ---------------------------------------------------------------------------
if [ ! -f .env ]; then
    cat <<EOF >&2
✗ .env is missing.

Copy the template and fill the two required tokens:

    cp config/.env.example .env

Required:
  TELEGRAM_BOT_TOKEN  — bot token from @BotFather
  SBC_TEAM_TOKEN      — team token from steppebusinessclub.com/hackathon

Then re-run ./scripts/run.sh.
EOF
    exit 1
fi

# Read .env into the current shell so the rest of the script can use the
# values. We don't `source` because that would also evaluate any quoted
# values; the manual loop is safer and tolerates spaces.
while IFS='=' read -r key value; do
    case "$key" in
        ''|\#*) continue ;;
        *) export "$key=${value%$'\r'}" ;;
    esac
done < .env

missing=""
for required in TELEGRAM_BOT_TOKEN SBC_TEAM_TOKEN; do
    if [ -z "${!required:-}" ]; then
        missing="$missing $required"
    fi
done
if [ -n "$missing" ]; then
    echo "✗ Missing required env in .env:$missing" >&2
    echo "  See config/.env.example for the full list." >&2
    exit 1
fi

SBC_MCP_URL="${SBC_MCP_URL:-https://www.steppebusinessclub.com/api/mcp}"
NGROK_AUTHTOKEN="${NGROK_AUTHTOKEN:-}"

echo "✓ .env validated"

# ---------------------------------------------------------------------------
# 2. Regenerate .mcp.json from .env (gitignored)
# ---------------------------------------------------------------------------
cat > .mcp.json <<EOF
{
  "mcpServers": {
    "happycake": {
      "type": "http",
      "url": "${SBC_MCP_URL}",
      "headers": {
        "X-Team-Token": "${SBC_TEAM_TOKEN}"
      }
    }
  }
}
EOF
echo "✓ .mcp.json generated from .env"

# ---------------------------------------------------------------------------
# 3. Ensure .claude/settings.local.json permissions allow mcp__happycake__*
# ---------------------------------------------------------------------------
SETTINGS=".claude/settings.local.json"
mkdir -p .claude
if [ ! -f "$SETTINGS" ]; then
    cat > "$SETTINGS" <<'EOF'
{
  "permissions": {
    "allow": ["mcp__happycake__*"]
  }
}
EOF
    echo "✓ created $SETTINGS with mcp__happycake__* permission"
else
    python3 - "$SETTINGS" <<'PY'
import json, sys
path = sys.argv[1]
with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)
perms = data.setdefault("permissions", {})
allow = perms.setdefault("allow", [])
needle = "mcp__happycake__*"
if needle not in allow:
    allow.append(needle)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print(f"  added {needle} to permissions.allow", flush=True)
else:
    print(f"  permissions.allow already grants {needle}", flush=True)
PY
fi

# ---------------------------------------------------------------------------
# 4. Install deps (idempotent — uv sync + npm install)
# ---------------------------------------------------------------------------
echo "▶ syncing Python deps (uv sync)…"
uv sync --quiet > data/uv-sync.log 2>&1 || {
    echo "  ✗ uv sync failed — see data/uv-sync.log" >&2
    exit 1
}
echo "  ✓ python deps ready"

echo "▶ installing web deps (npm install)…"
(
    cd web
    if [ ! -d node_modules ]; then
        npm install --silent > "$REPO_ROOT/data/npm-install.log" 2>&1
    fi
)
echo "  ✓ web deps ready"

# ---------------------------------------------------------------------------
# 5. Build web/ with relative API URLs
# ---------------------------------------------------------------------------
echo "▶ building web/ (PUBLIC_API_BASE='' for relative URLs)…"
(
    cd web
    PUBLIC_API_BASE= npm run build > "$REPO_ROOT/data/web-build.log" 2>&1 || {
        echo "  ✗ web build failed — see data/web-build.log" >&2
        exit 1
    }
)
echo "  ✓ web/dist/ ready"

# ---------------------------------------------------------------------------
# 6. Start uvicorn (FastAPI backend + storefront mount)
# ---------------------------------------------------------------------------
echo "▶ stopping any prior uvicorn / ngrok / bot processes…"
pkill -f "uvicorn src.webhooks.app" 2>/dev/null || true
pkill -f "ngrok http 8000" 2>/dev/null || true
pkill -f "python -m src.bot.app" 2>/dev/null || true
sleep 1

echo "▶ starting uvicorn on :8000…"
nohup uv run uvicorn src.webhooks.app:app --host 127.0.0.1 --port 8000 \
    > data/uvicorn.log 2>&1 &
UVICORN_PID=$!

cleanup() {
    echo
    echo "▶ stopping…"
    [ -n "${UVICORN_PID:-}" ] && kill "$UVICORN_PID" 2>/dev/null || true
    [ -n "${BOT_PID:-}" ] && kill "$BOT_PID" 2>/dev/null || true
    pkill -f "ngrok http 8000" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

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
    echo " ✗"
    echo "  uvicorn failed to start — see data/uvicorn.log" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 7. Start the Telegram bot (optional)
# ---------------------------------------------------------------------------
BOT_PID=""
if [ "$WITH_BOT" = "1" ]; then
    if ! command -v claude > /dev/null 2>&1; then
        echo "  ⚠  claude CLI not on PATH — bot will reply '(no response)' to free text"
    fi
    echo "▶ starting Telegram bot…"
    nohup uv run python -m src.bot.app > data/bot.log 2>&1 &
    BOT_PID=$!
    sleep 3
    if ! kill -0 "$BOT_PID" 2>/dev/null; then
        echo "  ✗ bot exited immediately — see data/bot.log" >&2
    else
        BOT_USERNAME=$(grep -m1 'Run polling for bot' data/bot.log 2>/dev/null \
            | sed -n 's/.*bot \(@[^ ]*\).*/\1/p' || true)
        echo "  ✓ bot polling${BOT_USERNAME:+ as $BOT_USERNAME}"
    fi
fi

# ---------------------------------------------------------------------------
# 8. Start ngrok (optional)
# ---------------------------------------------------------------------------
PUBLIC_URL=""
if [ "$WITH_NGROK" = "1" ]; then
    if ! command -v ngrok > /dev/null 2>&1; then
        echo "  ⚠ ngrok not on PATH — skipping public tunnel."
        WITH_NGROK=0
    fi
fi

if [ "$WITH_NGROK" = "1" ]; then
    if [ -n "$NGROK_AUTHTOKEN" ]; then
        ngrok config add-authtoken "$NGROK_AUTHTOKEN" > /dev/null 2>&1 || true
    fi
    echo "▶ starting ngrok on :8000…"
    nohup ngrok http 8000 --log=stdout > data/ngrok.log 2>&1 &
    NGROK_PID=$!

    echo -n "  waiting for ngrok"
    for _ in $(seq 1 30); do
        if curl -fsS http://127.0.0.1:4040/api/tunnels > /dev/null 2>&1; then
            echo " ✓"
            break
        fi
        echo -n "."
        sleep 0.5
    done

    for _ in $(seq 1 20); do
        # Use python -c so stdin (the curl pipe) is the body, not the script.
        PUBLIC_URL=$(curl -fsS http://127.0.0.1:4040/api/tunnels 2>/dev/null \
            | python3 -c '
import json, sys
try:
    tunnels = json.load(sys.stdin).get("tunnels") or []
except (json.JSONDecodeError, ValueError):
    tunnels = []
for t in tunnels:
    if t.get("proto") == "https" and t.get("public_url"):
        print(t["public_url"])
        break
' 2>/dev/null || true)
        if [ -n "$PUBLIC_URL" ]; then
            break
        fi
        sleep 0.5
    done
fi

# ---------------------------------------------------------------------------
# 9. Summary
# ---------------------------------------------------------------------------
echo
echo "──────────────────────────────────────────────────────────────"
echo " HappyCake demo is live."
echo "──────────────────────────────────────────────────────────────"
if [ -n "$PUBLIC_URL" ]; then
    echo " 🌐 Public URL:    $PUBLIC_URL"
    echo "   • Storefront:   $PUBLIC_URL"
    echo "   • Catalog:      $PUBLIC_URL/api/catalog"
    echo "   • Policies:     $PUBLIC_URL/api/policies"
    echo "   • OpenAPI:      $PUBLIC_URL/openapi.json"
    echo "   • agent.txt:    $PUBLIC_URL/agent.txt"
else
    echo " Local only (no ngrok)."
    echo "   • Storefront:   http://127.0.0.1:8000"
fi
if [ -n "$BOT_PID" ]; then
    echo " 🤖 Telegram bot:  ${BOT_USERNAME:-(check data/bot.log)}"
fi
echo " Logs: data/uvicorn.log, data/bot.log, data/ngrok.log"
echo " Press Ctrl-C to stop everything."
echo "──────────────────────────────────────────────────────────────"

# Block until Ctrl-C; trap tears down all background processes.
wait $UVICORN_PID
