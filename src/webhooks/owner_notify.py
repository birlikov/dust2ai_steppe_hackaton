"""Push a new-order summary to the owner's Telegram chat.

Extracted from :mod:`src.webhooks.app` so that module stays under 500 LOC.
Imported and called from :func:`src.webhooks.app.api_order`.

Usage::

    from src.webhooks.owner_notify import notify_owner_of_order, OrderNotifyPayload

    notify_payload = OrderNotifyPayload(
        customer_name=payload.customer.name,
        source=payload.source,
        items=[(item.quantity, item.slug) for item in payload.items],
        fulfillment_type=payload.fulfillment.type,
        fulfillment_at_iso=payload.fulfillment.at_iso,
    )
    await notify_owner_of_order(
        payload=notify_payload,
        order_id=order_id,
        ticket_id=ticket_id,
        total_cents=total_cents,
        kitchen_status=kitchen_status,
    )
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from pydantic import BaseModel

from src.bot.markdown import tg_normalise
from src.core.config import get_settings
from src.core.logging import get_logger
from src.storage import drafts

log = get_logger(__name__)

_SOURCE_EMOJI: dict[str, str] = {
    "website": "📦",
    "agent": "🤖",
    "whatsapp": "💬",
    "instagram": "📸",
    "telegram": "📨",
    "walk-in": "🚶",
}


class OrderNotifyPayload(BaseModel):
    """Typed view of the order data needed for the owner Telegram push.

    Decouples :mod:`src.webhooks.owner_notify` from the full
    :class:`src.webhooks.app.OrderRequest` model so there is no circular import.
    """

    customer_name: str
    source: str
    items: list[tuple[int, str]]  # (quantity, slug)
    fulfillment_type: str
    fulfillment_at_iso: str | None = None


async def notify_owner_of_order(
    *,
    payload: OrderNotifyPayload,
    order_id: str,
    ticket_id: str | None,
    total_cents: int,
    kitchen_status: str,
) -> None:
    """Push a one-line summary of the new order to the owner's Telegram.

    Use when: a new order is confirmed via ``/api/order`` and we want the
    owner to see it immediately without opening the dashboard.

    Do NOT use: for leads or Instagram drafts — those have their own paths.

    Best-effort: failures (no owner paired, Telegram down, missing token)
    log a warning and never raise. The customer order is already persisted
    before this is called, so a push failure is non-fatal.

    Returns:
        None (always; errors are logged, never raised).
    """
    try:
        owner = await drafts.get_owner()
        if owner is None:
            return
        token = get_settings().telegram_bot_token
        if not token:
            log.warning("order_notify.no_token")
            return

        emoji = _SOURCE_EMOJI.get(payload.source, "📦")
        lines: list[str] = [f"{qty}x {slug}" for qty, slug in payload.items]
        body_parts = [
            f"{emoji} *New order* — {payload.customer_name}",
            ", ".join(lines),
            (
                f"*${total_cents / 100:,.2f}* · {payload.fulfillment_type}"
                + (
                    f" at {payload.fulfillment_at_iso}"
                    if payload.fulfillment_at_iso
                    else ""
                )
            ),
            f"_order {order_id[:14]}_"
            + (f" · _ticket {ticket_id[:14]}_" if ticket_id else ""),
        ]
        if kitchen_status == "kitchen_pending":
            body_parts.append("_kitchen ticket pending — will retry shortly_")
        body = "\n".join(body_parts)

        # One-shot Bot — the polling bot lives in a separate process,
        # so we open/close a fresh session per push.
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        try:
            await bot.send_message(
                owner.telegram_chat_id,
                tg_normalise(body),
                parse_mode="Markdown",
            )
        finally:
            await bot.session.close()
    except Exception as exc:
        log.warning("order_notify.failed", err=str(exc))
