"""Seed three Instagram post drafts so ``/drafts`` has something to approve.

For each of the three brandbook content groups (Product, Audience,
Company), we:

  1. Ask :class:`ClaudeBridge` for a brand-voice caption.
  2. Schedule the post via ``instagram_schedule_post`` (returns a
     ``scheduledPostId``).
  3. Persist the draft locally via :mod:`src.storage.drafts` so the
     Telegram ``/drafts`` command can list / approve / reject it.

After this script, the owner can open the bot, send ``/drafts``, tap
Approve on each one, and watch the post flow through
``instagram_approve_post`` → ``instagram_publish_post`` (driven from
``src/bot/owner_commands.py``).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agents.claude_bridge import ClaudeBridgeError, build_default_bridge  # noqa: E402
from src.core.logging import get_logger  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)
from src.storage import drafts  # noqa: E402
from src.storage.db import get_connection  # noqa: E402

log = get_logger(__name__)


SEEDS: list[dict[str, str]] = [
    {
        "group": "Product",
        "image": "/brand/products/happy-cake-product-01.webp",
        "brief": (
            "Write an Instagram Product post for cake \"Honey\" — slice. "
            "Use brandbook reference 1 ('Cake \"Honey\" is back on the counter') "
            "as a stylistic anchor but do not copy it verbatim. Mention 1.2 kg, "
            "$42 if you reference the whole cake; for a slice mention $8.50 and "
            "individual size. End with the closing pattern."
        ),
    },
    {
        "group": "Audience",
        "image": "/brand/products/happy-cake-product-03.webp",
        "brief": (
            "Write an Instagram Audience post: a small guide for choosing a "
            "cake for ten guests. Use brandbook reference 2 as a style anchor. "
            "Numbered list. Specific quantities. End with the closing pattern."
        ),
    },
    {
        "group": "Company",
        "image": "/brand/hero/happy-cake-hero-01.webp",
        "brief": (
            "Write an Instagram Company post: a quiet, behind-the-scenes shot "
            "of the kitchen on a Tuesday morning. Use brandbook reference 3 as "
            "a style anchor. Mention Saule starting the honey biscuit at 6:30. "
            "Plain, unhyped. End with the closing pattern."
        ),
    },
]


async def _amain() -> int:
    bridge = build_default_bridge()
    async with build_default_client() as mcp:
        for seed in SEEDS:
            try:
                caption = await bridge.query(seed["brief"])
            except ClaudeBridgeError as exc:
                print(f"bridge failed for {seed['group']}: {exc}", file=sys.stderr)
                continue
            caption = caption.strip()
            if not caption:
                print(f"empty caption for {seed['group']}; skipping", file=sys.stderr)
                continue

            scheduled_id: str | None = None
            try:
                resp = await call_with_retry(
                    mcp,
                    "instagram_schedule_post",
                    {"imageUrl": seed["image"], "caption": caption},
                )
                if isinstance(resp, dict):
                    raw_id = resp.get("scheduledPostId") or resp.get("id")
                    scheduled_id = str(raw_id) if raw_id else None
            except (McpTransportError, McpError) as exc:
                print(
                    f"schedule_post failed for {seed['group']}: {exc}",
                    file=sys.stderr,
                )

            draft = await drafts.create(
                channel="instagram",
                kind="post",
                payload={
                    "group": seed["group"],
                    "imageUrl": seed["image"],
                    "caption": caption,
                },
            )
            if scheduled_id:
                # Stash the scheduledPostId on the draft so /drafts approval
                # can publish via instagram_approve_post + publish.
                conn = await get_connection()
                await conn.execute(
                    "UPDATE drafts SET external_id = ? WHERE id = ?",
                    (scheduled_id, draft.id),
                )
                await conn.commit()
            print(
                f"  draft {draft.id[:8]} ({seed['group']}) scheduled "
                f"as {scheduled_id or '<not scheduled>'}"
            )

    return 0


def main() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
