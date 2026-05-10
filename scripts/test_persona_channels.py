"""End-to-end channel test through the runtime persona.

Drives WhatsApp + Instagram + Google Business through the runtime persona
(``claude -p`` via the bridge) on the live MCP. For each channel:

  1. Inject inbound via ``whatsapp_inject_inbound`` / ``instagram_inject_dm``
     so evaluator counters tick.
  2. Run the Orchestrator with the same payload so the persona reasons
     about it (claude → MCP tools).
  3. Forward the persona's reply back through the MCP outbound tool
     (``whatsapp_send`` / ``instagram_send_dm`` / ``gb_simulate_reply``).
  4. Snapshot the evaluator at the end.

This proves the persona handles each channel end-to-end — not canned
strings, not just unit-mocked.

Usage:
    uv run python scripts/test_persona_channels.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agents.claude_bridge import build_default_bridge  # noqa: E402
from src.core.config import get_settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)
from src.workflows.orchestrator import Orchestrator, TurnRequest  # noqa: E402

log = get_logger(__name__)


async def amain() -> int:  # noqa: PLR0915 — single linear demo script
    settings = get_settings()
    out_dir = (REPO_ROOT / settings.sqlite_path.parent).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    bridge = build_default_bridge()
    print(f"bridge: claude CLI = {bridge.command}, model = {bridge.model}, "
          f"timeout = {bridge.timeout_s}s")

    orchestrator = Orchestrator(bridge=bridge)

    async with build_default_client() as mcp:
        replies: dict[str, str] = {}

        # ---- 1. WhatsApp ----------------------------------------------------
        wa_phone = "+12815550143"
        wa_text = 'Hi! Is the cake "Honey" available today, slice or whole?'
        print(f"\n▶ WhatsApp inbound from {wa_phone}: {wa_text!r}")
        await call_with_retry(
            mcp,
            "whatsapp_inject_inbound",
            {"from": wa_phone, "message": wa_text},
        )
        print("  ▷ persona reasoning…")
        wa_turn = await orchestrator.run(
            TurnRequest(
                channel="whatsapp",
                external_id=wa_phone,
                user_message=wa_text,
            )
        )
        replies["whatsapp"] = wa_turn.reply
        print(f"  ▷ persona replied ({len(wa_turn.reply)} chars): "
              f"{wa_turn.reply[:160]}…")
        await call_with_retry(
            mcp,
            "whatsapp_send",
            {"to": wa_phone, "message": wa_turn.reply},
        )
        print("  ✓ whatsapp_send delivered")

        # ---- 2. Instagram DM ------------------------------------------------
        ig_thread = "ig_persona_test_1"
        ig_text = "saw your napoleon — what size and price for 6 people?"
        print(f"\n▶ Instagram DM thread {ig_thread}: {ig_text!r}")
        await call_with_retry(
            mcp,
            "instagram_inject_dm",
            {"threadId": ig_thread, "from": "@persona_test", "message": ig_text},
        )
        print("  ▷ persona reasoning…")
        ig_turn = await orchestrator.run(
            TurnRequest(
                channel="instagram",
                external_id=f"dm:{ig_thread}",
                user_message=ig_text,
            )
        )
        replies["instagram"] = ig_turn.reply
        print(f"  ▷ persona replied ({len(ig_turn.reply)} chars): "
              f"{ig_turn.reply[:160]}…")
        await call_with_retry(
            mcp,
            "instagram_send_dm",
            {"threadId": ig_thread, "message": ig_turn.reply},
        )
        print("  ✓ instagram_send_dm delivered")

        # ---- 3. Google Business review reply --------------------------------
        try:
            reviews = await call_with_retry(mcp, "gb_list_reviews", {})
            review_list: list[dict] = []
            if isinstance(reviews, dict):
                review_list = reviews.get("reviews") or reviews.get("data") or []
            elif isinstance(reviews, list):
                review_list = reviews
            target = next(
                (r for r in review_list if r.get("rating") and r.get("id")),
                None,
            )
            if target is None:
                print("\n▶ Google Business: no reviews available, skipping")
            else:
                rid = str(target["id"])
                rtext = str(target.get("text") or target.get("comment") or "")
                rating = target.get("rating")
                print(
                    f"\n▶ GB review {rid} ({rating}★): {rtext[:140]}…"
                )
                gb_prompt = (
                    f"A Google Business review just arrived (rating {rating}/5):\n"
                    f"\"{rtext}\"\n\n"
                    f"Write the brand-voice reply (no closing pattern; this is a "
                    f"review reply not a feed post). Return only the reply text."
                )
                gb_turn = await orchestrator.run(
                    TurnRequest(
                        channel="gbusiness",
                        external_id=f"review:{rid}",
                        user_message=gb_prompt,
                    )
                )
                replies["gbusiness"] = gb_turn.reply
                print(
                    f"  ▷ persona replied ({len(gb_turn.reply)} chars): "
                    f"{gb_turn.reply[:160]}…"
                )
                await call_with_retry(
                    mcp,
                    "gb_simulate_reply",
                    {"reviewId": rid, "reply": gb_turn.reply},
                )
                print("  ✓ gb_simulate_reply delivered")
        except (McpTransportError, McpError) as exc:
            print(f"  ✗ GB step skipped: {exc}")

        # ---- 4. Snapshot ----------------------------------------------------
        print("\n▶ evaluator snapshot…")
        report: dict[str, object] = {
            "ranAt": datetime.now(UTC).isoformat(),
            "replies": replies,
        }
        for tool in (
            "evaluator_get_evidence_summary",
            "evaluator_score_channel_response",
            "evaluator_score_world_scenario",
        ):
            try:
                report[tool] = await call_with_retry(mcp, tool, {})
            except (McpTransportError, McpError) as exc:
                report[tool] = {"error": str(exc)}

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"scorecard_persona_{ts}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nscorecard → {out_path}")

    # Summary tail.
    counts = {}
    summary = report.get("evaluator_get_evidence_summary")
    if isinstance(summary, dict):
        counts = summary.get("counts") or {}
    score_world = report.get("evaluator_score_world_scenario")
    score_channel = report.get("evaluator_score_channel_response")
    print("\nKey counters:")
    for k in (
        "whatsappInbound",
        "whatsappOutbound",
        "instagramActions",
        "gbusinessReplies",
        "auditCalls",
    ):
        print(f"  {k}: {counts.get(k)}")
    if isinstance(score_channel, dict):
        print(f"  channel_response score: {score_channel.get('score')}")
    if isinstance(score_world, dict):
        print(f"  world_scenario score: {score_world.get('score')}")

    return 0


def main() -> None:
    sys.exit(asyncio.run(amain()))


if __name__ == "__main__":
    main()
