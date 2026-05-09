"""Mock customer interactions on WhatsApp + Instagram + Google Business.

Direct MCP calls (no LLM, no scenario engine), so this script is fast and
deterministic. Each interaction bumps a different evaluator counter:

  whatsapp_inject_inbound  → ``whatsappInbound``
  whatsapp_send            → ``whatsappOutbound``
  instagram_inject_dm      → ``instagramActions``
  instagram_send_dm        → ``instagramActions``
  gb_simulate_reply        → ``gbusinessReplies`` (per review id)

Brand-voice replies are canned (mirroring `agent/EXAMPLES.md` reference
posts) so the harness is reproducible. Run after a fresh
``world_start_scenario`` if the simulator state was reset; otherwise
counters just stack on top of the prior run.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.logging import get_logger  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)

log = get_logger(__name__)


WHATSAPP_THREADS = [
    {
        "from": "+12815550100",
        "inbound": "Hi! Do you have cake \"Honey\" today?",
        "reply": (
            "Hi, friend — yes, the cake \"Honey\" is on the counter, 1.2 kg, "
            "$42, ready through Sunday. Want me to set one aside?"
        ),
    },
    {
        "from": "+12815550199",
        "inbound": "Custom cake for Saturday possible?",
        "reply": (
            "Hi — custom cakes go through Saule directly. Tell us the name "
            "you'd like written on top and we'll be back within the hour."
        ),
    },
]

INSTAGRAM_THREADS = [
    {
        "thread_id": "ig_thread_demo_1",
        "from": "@maya_sugarland",
        "inbound": "love your honey cake. can I order one for tomorrow?",
        "reply": (
            "Hi, Maya — yes, the cake \"Honey\" 1.2 kg, $42 is bakeable for "
            "tomorrow. Pickup or delivery?"
        ),
    },
]


async def _safe(
    mcp: object,
    tool: str,
    args: dict[str, object] | None = None,
    *,
    label: str | None = None,
) -> object:
    try:
        result = await call_with_retry(mcp, tool, args or {})  # type: ignore[arg-type]
        print(f"  ✓ {label or tool}")
        return result
    except (McpTransportError, McpError) as exc:
        print(f"  ✗ {label or tool}: {exc}", file=sys.stderr)
        return None


async def _amain() -> int:
    async with build_default_client() as mcp:
        print("▶ WhatsApp inbound + replies…")
        for t in WHATSAPP_THREADS:
            await _safe(
                mcp,
                "whatsapp_inject_inbound",
                {"from": t["from"], "message": t["inbound"]},
                label=f"WA inject {t['from']}",
            )
            await _safe(
                mcp,
                "whatsapp_send",
                {"to": t["from"], "message": t["reply"]},
                label=f"WA reply {t['from']}",
            )

        print("▶ Instagram DM inbound + reply…")
        for t in INSTAGRAM_THREADS:
            await _safe(
                mcp,
                "instagram_inject_dm",
                {
                    "threadId": t["thread_id"],
                    "from": t["from"],
                    "message": t["inbound"],
                },
                label=f"IG inject {t['thread_id']}",
            )
            await _safe(
                mcp,
                "instagram_send_dm",
                {"threadId": t["thread_id"], "message": t["reply"]},
                label=f"IG reply {t['thread_id']}",
            )

        print("▶ Google Business reviews + replies…")
        reviews = await _safe(mcp, "gb_list_reviews", label="gb_list_reviews")
        if isinstance(reviews, list):
            for review in reviews:
                if not isinstance(review, dict):
                    continue
                review_id = review.get("id")
                if not review_id:
                    continue
                rating = review.get("rating", 0)
                reply = (
                    "Thank you, friend — that's lovely to hear. — the HappyCake team"
                    if rating >= 4
                    else (
                        "I'm sorry — that's on us. Could you send us a message on "
                        "WhatsApp so Saule can make it right? — the HappyCake team"
                    )
                )
                await _safe(
                    mcp,
                    "gb_simulate_reply",
                    {"reviewId": review_id, "reply": reply},
                    label=f"GB reply {review_id} ({rating}★)",
                )

        print("\n▶ Snapshot…")
        evidence = await _safe(
            mcp, "evaluator_get_evidence_summary", label="evidence"
        )
        score = await _safe(
            mcp, "evaluator_score_channel_response", label="score:channel_response"
        )
        composite = await _safe(
            mcp,
            "evaluator_generate_team_report",
            {
                "repoUrl": "https://github.com/birlikov/dust2ai_steppe_hackaton",
                "websiteUrl": "https://happycake.us",
            },
            label="composite",
        )
        if isinstance(evidence, dict):
            counts = evidence.get("counts", {})
            print(
                "  counts:",
                json.dumps(
                    {k: counts[k] for k in counts if isinstance(counts[k], int)},
                    indent=2,
                ),
            )
        if isinstance(score, dict):
            print(f"  channel_response: {score.get('score')}/{score.get('maxScore')}")
        if isinstance(composite, dict):
            print(f"  composite: {composite.get('score')}/{composite.get('maxScore')}")
    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
