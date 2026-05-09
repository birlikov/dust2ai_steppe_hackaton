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
    """Free-text from the owner. Streams agent progress through Telegram."""
    text = message.text
    if not text:
        await message.answer("(text-only for now)")
        return

    await bot.send_chat_action(message.chat.id, "typing")

    history = await _load_history(session_id)
    progress: dict[str, str] = {}  # tool_use_id → display name (mutating tools only)

    async def on_event(event: dict[str, object]) -> None:
        # Forward only the events that make the owner's wait legible. Skip
        # text-deltas (too noisy), system/init lines, and read-only tools.
        etype = event.get("type")
        if etype == "stream_event":
            inner = event.get("event") or {}
            if not isinstance(inner, dict):
                return
            block = inner.get("content_block") or {}
            if (
                inner.get("type") == "content_block_start"
                and isinstance(block, dict)
                and block.get("type") == "tool_use"
            ):
                tool_name = block.get("name", "")
                tool_id = block.get("id", "")
                if not isinstance(tool_name, str) or not isinstance(tool_id, str):
                    return
                if _is_mutating_tool(tool_name):
                    progress[tool_id] = _friendly_tool_name(tool_name)
                    await message.answer(f"▶ {progress[tool_id]}…")
            return
        if etype == "user":
            msg = event.get("message") or {}
            if not isinstance(msg, dict):
                return
            for c in msg.get("content", []) or []:
                if not isinstance(c, dict):
                    continue
                if c.get("type") == "tool_result":
                    tool_id = c.get("tool_use_id", "")
                    if isinstance(tool_id, str) and tool_id in progress:
                        await message.answer(f"✓ {progress[tool_id]} done.")
                        progress.pop(tool_id, None)

    try:
        reply_text = await owner_bridge.query_streaming(
            text, on_event, history=history
        )
    except ClaudeBridgeError as exc:
        log.error("owner_bridge.stream_failed", err=str(exc))
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


# Mutating MCP tools — surfaced to the owner so they see what the bot did.
# Read-only tools (catalog, capacity, evidence-summary, etc.) stay silent
# to keep Telegram from spamming during a multi-tool turn.
_MUTATING_TOOL_PREFIXES: tuple[str, ...] = (
    "mcp__happycake__square_create_order",
    "mcp__happycake__square_update_order_status",
    "mcp__happycake__kitchen_create_ticket",
    "mcp__happycake__kitchen_accept_ticket",
    "mcp__happycake__kitchen_reject_ticket",
    "mcp__happycake__kitchen_mark_ready",
    "mcp__happycake__marketing_create_campaign",
    "mcp__happycake__marketing_launch_simulated_campaign",
    "mcp__happycake__marketing_generate_leads",
    "mcp__happycake__marketing_route_lead",
    "mcp__happycake__marketing_adjust_campaign",
    "mcp__happycake__marketing_report_to_owner",
    "mcp__happycake__whatsapp_send",
    "mcp__happycake__whatsapp_register_webhook",
    "mcp__happycake__instagram_send_dm",
    "mcp__happycake__instagram_reply_to_comment",
    "mcp__happycake__instagram_schedule_post",
    "mcp__happycake__instagram_approve_post",
    "mcp__happycake__instagram_publish_post",
    "mcp__happycake__instagram_register_webhook",
    "mcp__happycake__gb_simulate_reply",
    "mcp__happycake__gb_simulate_post",
    "mcp__happycake__world_start_scenario",
    "mcp__happycake__world_advance_time",
    "mcp__happycake__world_inject_event",
)


def _is_mutating_tool(name: str) -> bool:
    return any(name.startswith(p) for p in _MUTATING_TOOL_PREFIXES)


def _friendly_tool_name(name: str) -> str:
    """Render an mcp__happycake__square_create_order → 'Creating Square order'."""
    base = name.removeprefix("mcp__happycake__")
    pretty_map = {
        "square_create_order": "Creating Square order",
        "square_update_order_status": "Updating order status",
        "kitchen_create_ticket": "Sending kitchen ticket",
        "kitchen_accept_ticket": "Accepting kitchen ticket",
        "kitchen_reject_ticket": "Rejecting kitchen ticket",
        "kitchen_mark_ready": "Marking order ready",
        "marketing_create_campaign": "Creating campaign",
        "marketing_launch_simulated_campaign": "Launching campaign",
        "marketing_generate_leads": "Generating leads",
        "marketing_route_lead": "Routing lead",
        "marketing_adjust_campaign": "Adjusting campaign",
        "marketing_report_to_owner": "Filing owner report",
        "whatsapp_send": "Sending WhatsApp message",
        "instagram_send_dm": "Sending Instagram DM",
        "instagram_reply_to_comment": "Replying to Instagram comment",
        "instagram_schedule_post": "Scheduling Instagram post",
        "instagram_approve_post": "Approving Instagram post",
        "instagram_publish_post": "Publishing Instagram post",
        "gb_simulate_reply": "Replying to Google review",
        "gb_simulate_post": "Posting to Google Business",
    }
    return pretty_map.get(base, f"Calling {base}")


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
