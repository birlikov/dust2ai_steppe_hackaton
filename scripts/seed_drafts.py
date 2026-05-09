"""Seed three Instagram post drafts so ``/drafts`` has something to approve.

For each of the three brandbook content groups (Product, Audience,
Company) we:

  1. Use a canned brand-voice caption (the runtime persona regenerates
     fresher copy at scenario time; here we want determinism + speed so
     the demo is fast and idempotent).
  2. Schedule the post via ``instagram_schedule_post`` — this is the
     call the evaluator counts as ``instagramActions``.
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
        "caption": (
            'Cake "Honey" is back on the counter.\n\n'
            "Six layers of golden honey biscuit, soft custard between "
            "every one, walnuts pressed lightly into the top. Same "
            "recipe as the day we opened.\n\n"
            "1.2 kg, $42, ready through Sunday.\n\n"
            "Order on the site at happycake.us or send a message on "
            "WhatsApp."
        ),
    },
    {
        "group": "Audience",
        "image": "/brand/products/happy-cake-product-03.webp",
        "caption": (
            "Choosing a cake for ten guests — a small guide.\n\n"
            "1. Plan for one slice per person, plus three for seconds. "
            "A 1.2 kg cake serves ten comfortably.\n"
            "2. If half the guests are children, our cake \"Milk "
            "Maiden\" is the safer bet — light, mild, rarely refused.\n"
            "3. If you're celebrating with adults who like coffee, try "
            "the cake \"Tiramisu\".\n"
            "4. Order 24 hours ahead so we can bake to you, not from "
            "stock.\n\n"
            "Order on the site at happycake.us or send a message on "
            "WhatsApp."
        ),
    },
    {
        "group": "Company",
        "image": "/brand/hero/happy-cake-hero-01.webp",
        "caption": (
            "Tuesday morning at HappyCake Sugar Land.\n\n"
            "Saule starts the honey biscuit at 6:30. The walnuts are "
            "toasted in small batches. By 9:00 the first cake \"Honey\" "
            "is cooling on the rack and the shop opens.\n\n"
            "No shortcuts. No mixes. The taste your grandmother would "
            "recognise.\n\n"
            "Today's bake is out. See you on the counter, or order "
            "online at happycake.us."
        ),
    },
]


async def _amain() -> int:
    async with build_default_client() as mcp:
        for seed in SEEDS:
            scheduled_id: str | None = None
            try:
                resp = await call_with_retry(
                    mcp,
                    "instagram_schedule_post",
                    {"imageUrl": seed["image"], "caption": seed["caption"]},
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
                    "caption": seed["caption"],
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
