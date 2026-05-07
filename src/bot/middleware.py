"""aiogram middleware: log inbound messages to the audit trail."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from src.core.logging import get_logger
from src.storage.audit import record
from src.storage.sessions import get_or_create

log = get_logger(__name__)


class AuditMiddleware(BaseMiddleware):
    """Records every inbound message into the audit log + ensures a session exists."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Message) and event.from_user is not None:
            session = await get_or_create("telegram", str(event.chat.id))
            data["session_id"] = session.id
            await record(
                "user",
                "inbound",
                {"text": event.text or "", "chat_id": event.chat.id},
                session_id=session.id,
            )
            log.info(
                "telegram.inbound",
                chat_id=event.chat.id,
                user_id=event.from_user.id,
                text_len=len(event.text or ""),
            )
        return await handler(event, data)
