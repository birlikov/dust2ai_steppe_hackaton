"""Passphrase-based pairing for the owner bot.

If ``OWNER_PASSPHRASE`` is set in the environment, the bot only dispatches
inbound updates to handlers when:

  - the chat is the paired owner's (``drafts.get_owner()``), OR
  - the chat sends a message containing the exact passphrase, in which
    case it gets paired and granted access from then on.

Otherwise the middleware short-circuits with a polite *"unlock with the
passphrase"* reply — the handler chain never runs. If ``OWNER_PASSPHRASE``
is empty, the bot stays open (dev / fresh-clone mode).

Registration order in ``src/bot/app.py``:

    dp.update.middleware(AuditMiddleware())   # injects session_id
    dp.update.middleware(AuthMiddleware())    # gates on the passphrase
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import (
    CallbackQuery,
    InaccessibleMessage,
    Message,
    TelegramObject,
    Update,
)

from src.core.config import get_settings
from src.core.logging import get_logger
from src.storage import drafts

log = get_logger(__name__)


class AuthMiddleware(BaseMiddleware):
    """Gate every inbound update on the owner passphrase."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        passphrase = get_settings().owner_passphrase.strip()
        if not passphrase:
            # Open mode — no gate.
            return await handler(event, data)

        message = _extract_message(event)
        callback = _extract_callback(event)
        chat_id = _resolve_chat_id(message, callback)
        if chat_id is None:
            # Can't identify the chat — reject silently.
            return None

        owner = await drafts.get_owner()
        if owner is not None and owner.telegram_chat_id == chat_id:
            return await handler(event, data)

        text = (message.text if message else "") or ""
        if passphrase and text.strip() == passphrase:
            username = message.from_user.username if message and message.from_user else None
            await drafts.remember_owner(chat_id=chat_id, username=username)
            log.info("auth.paired", chat_id=chat_id)
            if message is not None:
                await message.answer(
                    "Paired. You're the owner now. Ask me anything — "
                    "*sales today?*, *anything urgent?* — or use /help.",
                    parse_mode="Markdown",
                )
            return None

        # Not paired and no passphrase — refuse.
        if message is not None:
            await message.answer(
                "This bot is paired to its owner. "
                "Reply with the passphrase to unlock."
            )
        elif callback is not None:
            await callback.answer(
                "Locked — pair via passphrase first.", show_alert=True
            )
        log.info("auth.refused", chat_id=chat_id)
        return None


def _extract_message(event: TelegramObject) -> Message | None:
    if isinstance(event, Update):
        return event.message
    if isinstance(event, Message):
        return event
    return None


def _extract_callback(event: TelegramObject) -> CallbackQuery | None:
    if isinstance(event, Update):
        return event.callback_query
    if isinstance(event, CallbackQuery):
        return event
    return None


def _resolve_chat_id(
    message: Message | None, callback: CallbackQuery | None
) -> int | None:
    if message is not None:
        return message.chat.id
    if callback is not None:
        msg = callback.message
        if isinstance(msg, Message | InaccessibleMessage):
            return msg.chat.id
        return callback.from_user.id
    return None
