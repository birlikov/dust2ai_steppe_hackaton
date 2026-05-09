#!/usr/bin/env bash
# End-to-end demo of the HappyCake AI system.
#
#   1. Start the FastAPI storefront API on :8000 in the background.
#   2. Drive the marketing loop end-to-end (creates campaigns, generates
#      leads, routes them, files an owner report).
#   3. Reply to all seeded Google Business reviews via the runtime persona.
#   4. Generate three Instagram post drafts (Product / Audience / Company)
#      and schedule them — owner can approve via /drafts in Telegram.
#   5. Drive the world-engine scenario end-to-end and self-grade via the
#      five evaluator_score_* tools + evaluator_get_evidence_summary.
#   6. Save the final team report to data/team_report.json.
#
# Usage:  ./scripts/demo.sh
#
# Requirements:
#   - .env with TELEGRAM_BOT_TOKEN and SBC_TEAM_TOKEN populated
#   - claude CLI on PATH (the bridge subprocesses it)
#   - uv (the project's venv manager)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

mkdir -p data

echo "▶ starting storefront API on :8000…"
uv run uvicorn src.webhooks.app:app --host 127.0.0.1 --port 8000 \
    > data/uvicorn.log 2>&1 &
UVICORN_PID=$!
trap 'echo "▶ stopping uvicorn (pid $UVICORN_PID)"; kill $UVICORN_PID 2>/dev/null || true' EXIT

# Give uvicorn a moment to bind.
sleep 2
if ! curl -fsS http://127.0.0.1:8000/health > /dev/null; then
    echo "uvicorn failed to start — see data/uvicorn.log" >&2
    exit 1
fi
echo "  uvicorn ready (pid $UVICORN_PID)"

echo "▶ seeding marketing loop…"
uv run python scripts/seed_marketing.py

echo "▶ replying to Google Business reviews…"
uv run python scripts/seed_review_replies.py

echo "▶ seeding Instagram drafts…"
uv run python scripts/seed_drafts.py

echo "▶ driving world-engine scenario…"
uv run python scripts/run_scenario.py --max-events 40 --advance-each 30

echo "▶ generating evaluator team report…"
uv run python - <<'PY'
import asyncio, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent if "__file__" in globals() else "."))

from src.mcp.http_client import build_default_client, call_with_retry, McpError, McpTransportError


async def main() -> None:
    async with build_default_client() as mcp:
        try:
            report = await call_with_retry(mcp, "evaluator_generate_team_report", {})
        except (McpTransportError, McpError) as exc:
            print(f"evaluator_generate_team_report failed: {exc}", file=sys.stderr)
            sys.exit(2)
    Path("data/team_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("data/team_report.json written")


asyncio.run(main())
PY

echo "✓ demo complete. artefacts:"
ls -1 data/scorecard_*.json 2>/dev/null | tail -1
ls -1 data/team_report.json 2>/dev/null
