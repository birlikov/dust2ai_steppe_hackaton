"""Command and message handlers for the owner-facing Telegram bot.

The plain-message handler is a placeholder — once workflows are wired (post
brief unsealing), it dispatches to the agent loop. Until then it echoes a
diagnostic so the bot is visibly alive during dry-runs.
"""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.core.logging import get_logger
from src.storage.audit import record

router = Router(name="commands")
log = get_logger(__name__)

HELP_TEXT = (
    "Available commands:\n"
    "/start    — begin a session\n"
    "/help     — show this message\n"
    "/cancel   — cancel the current operation\n"
    "/restart  — wipe state and start over\n"
)


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session_id: str) -> None:
    await state.clear()
    await message.answer(
        "Ready. I'm your operations assistant.\n"
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
    await message.answer("Reset. Fresh start. Send /help for options.")
    await record("agent", "outbound", {"text": "restart"}, session_id=session_id)


@router.message()
async def echo_placeholder(message: Message, session_id: str) -> None:
    """Diagnostic echo until the agent loop is wired in."""
    text = message.text or "(non-text message)"
    reply = f"[stub] received: {text}"
    await message.answer(reply)
    await record("agent", "outbound", {"text": reply}, session_id=session_id)
