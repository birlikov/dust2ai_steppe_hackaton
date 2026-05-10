"""aiogram middleware: ensure a session exists for every inbound update.

Runs on **all** update types (messages and callback queries from inline
keyboards). Without this, callback handlers that declare ``session_id: str``
silently fail to dispatch — aiogram can't satisfy the parameter and the
handler is never called, which is what was killing the /inbox Approve / Edit
/ Reject taps.
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

from src.core.logging import get_logger
from src.storage.audit import record
from src.storage.sessions import get_or_create

log = get_logger(__name__)


class AuditMiddleware(BaseMiddleware):
    """Inject ``session_id`` for every inbound update + record the inbound."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        external_id, label, text = _resolve(event)
        if external_id is not None:
            session = await get_or_create("telegram", external_id)
            data["session_id"] = session.id
            await record(
                "user",
                "inbound",
                {"text": text, "external_id": external_id, "kind": label},
                session_id=session.id,
            )
            log.info(
                "telegram.inbound",
                kind=label,
                external_id=external_id,
                text_len=len(text),
            )
        return await handler(event, data)


def _resolve(event: TelegramObject) -> tuple[str | None, str, str]:
    """Return ``(external_id, kind, text)`` or ``(None, "?", "")`` for unknown."""
    # Aiogram wraps every incoming update in an ``Update`` envelope; unwrap.
    if isinstance(event, Update):
        if event.message is not None:
            return _from_message(event.message)
        if event.callback_query is not None:
            return _from_callback(event.callback_query)
        return None, "update", ""
    if isinstance(event, Message):
        return _from_message(event)
    if isinstance(event, CallbackQuery):
        return _from_callback(event)
    return None, "other", ""


def _from_message(message: Message) -> tuple[str | None, str, str]:
    if message.from_user is None:
        return None, "message", ""
    return str(message.chat.id), "message", message.text or ""


def _from_callback(callback: CallbackQuery) -> tuple[str | None, str, str]:
    text = callback.data or ""
    msg = callback.message
    if isinstance(msg, Message | InaccessibleMessage):
        return str(msg.chat.id), "callback", text
    # ``msg`` is ``None`` — fall back to the tapping user's id so a session
    # still exists and the handler can dispatch.
    return str(callback.from_user.id), "callback", text
