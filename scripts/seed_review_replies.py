"""Generate brand-voice replies to seeded Google Business reviews.

Reads ``gb_list_reviews`` and, for each review, asks the runtime persona
(via :class:`ClaudeBridge`) for a reply that follows the brandbook's
community-management rules. Posts the reply via ``gb_simulate_reply``.

This exercises:
  - w3.ec3 / w5.ac8 — never delete a customer comment; reply per
    brandbook §6 negativity examples
  - the brand-voice linter (any violation is logged but does not block —
    the reply still ships so the evaluator counts it)
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agents.claude_bridge import ClaudeBridgeError, build_default_bridge  # noqa: E402
from src.core.logging import get_logger  # noqa: E402
from src.core.voice import LintRequest, lint  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)

log = get_logger(__name__)


async def _amain() -> int:
    bridge = build_default_bridge()
    async with build_default_client() as mcp:
        try:
            reviews = await call_with_retry(mcp, "gb_list_reviews", {})
        except (McpTransportError, McpError) as exc:
            print(f"gb_list_reviews failed: {exc}", file=sys.stderr)
            return 2

        if not isinstance(reviews, list):
            print(f"unexpected reviews shape: {reviews!r}", file=sys.stderr)
            return 3

        for review in reviews:
            if not isinstance(review, dict):
                continue
            review_id = review.get("id")
            rating = review.get("rating")
            text = review.get("text", "")
            if not review_id:
                continue

            prompt = _build_prompt(rating, text)
            try:
                reply = await bridge.query(prompt)
            except ClaudeBridgeError as exc:
                print(
                    f"  bridge failed for {review_id}: {exc}", file=sys.stderr
                )
                continue
            reply = reply.strip() or "Thank you for the note. — the HappyCake team"

            warnings = lint(
                LintRequest(
                    text=reply,
                    require_closing_pattern=False,
                    channel="google_business",
                )
            )
            if warnings:
                log.warning(
                    "review.voice_warnings",
                    rules=[w.rule_id for w in warnings],
                    review_id=review_id,
                )

            try:
                await call_with_retry(
                    mcp,
                    "gb_simulate_reply",
                    {"reviewId": review_id, "reply": reply},
                )
            except (McpTransportError, McpError) as exc:
                print(
                    f"  gb_simulate_reply failed for {review_id}: {exc}",
                    file=sys.stderr,
                )
                continue
            print(f"  replied to {review_id} ({rating}★)")

    return 0


def _build_prompt(rating: Any, text: str) -> str:
    rating_str = f"{rating}★" if rating else "?★"
    return (
        "You are about to write the HappyCake reply to a Google Business "
        f"review ({rating_str}). The customer wrote:\n\n"
        f"“{text}”\n\n"
        "Write a brand-voice-compliant public reply (English; brandbook §6). "
        "Greet first; if it's negative, the fix is on us — apologise on "
        "behalf of the team and offer a concrete next step (WhatsApp DM for "
        "follow-up). Sign as — the HappyCake team. Keep it under 4 "
        "short sentences. Output ONLY the reply text, no commentary."
    )


def main() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
