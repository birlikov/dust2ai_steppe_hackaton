"""Command and message handlers for the owner-facing Telegram bot.

Plain-message handler hands the user's text to the runtime persona via
:class:`ClaudeBridge` (which shells out to ``claude -p``). The bridge owns the
system prompt — handlers don't see it.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.logging import get_logger
from src.core.voice import LintRequest, lint
from src.storage import drafts, sessions
from src.storage.audit import record

router = Router(name="commands")
log = get_logger(__name__)

HELP_TEXT = (
    "I'm your operations assistant — talk to me about the business.\n\n"
    "Examples:\n"
    "  • \"anything urgent?\"\n"
    "  • \"sales today?\"\n"
    "  • \"how's the kitchen?\"\n"
    "  • \"what's pending my approval?\"\n\n"
    "Or use a shortcut:\n"
    "  /dashboard  — today's sales + kitchen + what's urgent\n"
    "  /budget     — marketing budget + recent website leads\n"
    "  /drafts     — Instagram drafts waiting for your Approve / Edit / Reject\n"
    "  /restart    — clear my conversation memory\n"
    "  /cancel     — cancel the current step\n"
)

HISTORY_CAP = 24  # last N user/assistant text turns persisted per session


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session_id: str) -> None:
    await state.clear()
    await sessions.merge_state(session_id, {"messages": []})
    if message.from_user is not None:
        await drafts.remember_owner(
            chat_id=message.chat.id,
            username=message.from_user.username,
        )
    await message.answer(
        "Ready. I'm your HappyCake operations assistant.\n"
        "Send /help to see what I can do."
    )
    await record("agent", "outbound", {"text": "start ack"}, session_id=session_id)


@router.message(Command("help"))
async def cmd_help(message: Message, session_id: str) -> None:
    await message.answer(HELP_TEXT)
    await record("agent", "outbound", {"text": "help"}, session_id=session_id)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext, session_id: str) -> None:
    current = await state.get_state()
    if current is None:
        await message.answer("Nothing to cancel.")
    else:
        await state.clear()
        await message.answer("Cancelled. Send /help for next steps.")
    await record(
        "agent", "outbound", {"text": "cancel", "prior_state": current}, session_id=session_id
    )


@router.message(Command("restart"))
async def cmd_restart(message: Message, state: FSMContext, session_id: str) -> None:
    await state.clear()
    await sessions.merge_state(session_id, {"messages": []})
    await message.answer("Reset. Fresh start. Send /help for options.")
    await record("agent", "outbound", {"text": "restart"}, session_id=session_id)


@router.message(Command("logout"))
async def cmd_logout(message: Message, session_id: str) -> None:
    """Clear the owner pairing. Next message must re-pair via passphrase."""
    await drafts.forget_owner()
    await message.answer(
        "Unpaired. The next message must include the passphrase to unlock."
    )
    await record(
        "agent",
        "outbound",
        {"text": "logout", "chat_id": message.chat.id},
        session_id=session_id,
    )


@router.message()
async def message_handler(
    message: Message,
    bot: Bot,
    session_id: str,
    owner_bridge: ClaudeBridge,
) -> None:
    """Free-text from the owner. Routes through the ops persona."""
    text = message.text
    if not text:
        await message.answer("(text-only for now)")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    history = await _load_history(session_id)
    try:
        reply_text = await owner_bridge.query(text, history=history)
    except ClaudeBridgeError as exc:
        log.error("owner_bridge.query_failed", err=str(exc))
        await message.answer(
            "Couldn't reach the assistant just now — try again in a moment."
        )
        await record(
            "system", "error", {"reason": str(exc)}, session_id=session_id
        )
        return

    reply_text = reply_text or "(no response)"
    voice_warnings = lint(LintRequest(text=reply_text, channel="telegram"))
    await message.answer(reply_text)
    await _append_history(session_id, history, text, reply_text)
    await record(
        "agent",
        "outbound",
        {
            "text": reply_text,
            "voice_warnings": [v.rule_id for v in voice_warnings],
        },
        session_id=session_id,
    )


async def _load_history(session_id: str) -> list[dict[str, Any]]:
    sess = await sessions.get_by_id(session_id)
    if sess is None:
        return []
    return list(sess.state.get("messages", []))


async def _append_history(
    session_id: str,
    history: list[dict[str, Any]],
    user_text: str,
    assistant_text: str,
) -> None:
    new_history = [
        *history,
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]
    capped = new_history[-HISTORY_CAP:]
    await sessions.merge_state(session_id, {"messages": capped})
