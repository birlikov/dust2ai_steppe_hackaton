"""Command and message handlers for the owner-facing Telegram bot.

The plain-message handler dispatches to the Anthropic agent loop. The system
prompt is a generic placeholder until the brief unlocks; the workflow router
replaces it at H+0.
"""

from __future__ import annotations

from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from src.agents.loop import AgentLoop
from src.core.logging import get_logger
from src.storage import sessions
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

# Generic system prompt; replaced by workflow router at H+0.
DEFAULT_SYSTEM_PROMPT = (
    "You are an operations assistant for a small business owner. "
    "Until the four workflows are configured, answer briefly and "
    "conversationally. Be concise — one or two short paragraphs at most. "
    "Never invent customer data; if you'd need a tool you don't have, say so."
)

HISTORY_CAP = 20  # last N user/assistant text turns kept in session.state


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, session_id: str) -> None:
    await state.clear()
    await sessions.merge_state(session_id, {"messages": []})
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
    await sessions.merge_state(session_id, {"messages": []})
    await message.answer("Reset. Fresh start. Send /help for options.")
    await record("agent", "outbound", {"text": "restart"}, session_id=session_id)


@router.message()
async def message_handler(
    message: Message,
    bot: Bot,
    session_id: str,
    agent: AgentLoop,
) -> None:
    """Dispatch a free-text message through the agent loop."""
    text = message.text
    if not text:
        await message.answer("(text-only for now)")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    history = await _load_history(session_id)
    try:
        reply = await agent.run(
            system=DEFAULT_SYSTEM_PROMPT,
            user_message=text,
            history=history,  # type: ignore[arg-type]
        )
    except Exception as exc:
        log.exception("agent.run_failed")
        await message.answer("Hit an error reaching the model. Try again in a moment.")
        await record(
            "system", "error", {"reason": str(exc)}, session_id=session_id
        )
        return

    reply_text = reply.text or "(no response)"
    await message.answer(reply_text)
    await _append_history(session_id, history, text, reply_text)
    await record(
        "agent",
        "outbound",
        {
            "text": reply_text,
            "iters": reply.iterations,
            "stopped_for": reply.stopped_for,
            "tool_calls": [c["name"] for c in reply.tool_calls],
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
