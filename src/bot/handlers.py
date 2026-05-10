"""Command and message handlers for the owner-facing Telegram bot.

Plain-message handler hands the user's text to the runtime persona via
:class:`ClaudeBridge` (which shells out to ``claude -p``). The bridge owns the
system prompt — handlers don't see it.
"""

from __future__ import annotations

import json as _json
import re as _re
from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.bot.keyboards import (
    CB_NOTIFY_PREFIX,
    notify_keyboard,
    parse_notify_callback,
)
from src.bot.markdown import tg_normalise
from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.voice import LintRequest, lint
from src.storage import drafts, sessions
from src.storage.audit import record
from src.storage.db import get_connection

_SECS_PER_MIN = 60
_SECS_PER_HOUR = 3600
_SECS_PER_DAY = 86400

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
    "  /dashboard       — today's sales + kitchen + what's urgent\n"
    "  /budget          — marketing budget + recent website leads (priority-scored)\n"
    "  /inbox           — posts waiting for your Approve / Edit / Reject\n"
    "  /notify          — set push cadence (tap a preset: 1m / 30m / 2h / off)\n"
    "  /refund          — pick an order + queue a refund offer (or /refund <id>)\n"
    "  /drain_threads   — drain unanswered customer threads through the persona\n"
    "  /restart         — clear my conversation memory\n"
    "  /cancel          — cancel the current step\n"
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
    try:
        await message.answer(HELP_TEXT, parse_mode="Markdown")
    except Exception as exc:
        log.warning("help.markdown_failed", err=str(exc))
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


@router.message(Command("notify"))
async def cmd_notify(message: Message, session_id: str) -> None:
    """Configure the proactive-push cadence.

    Usage:
      ``/notify``                  → show current setting + tap-to-pick keyboard
      ``/notify 1m | 30m | 2h``    → set interval directly (60s ≤ x ≤ 24h)
      ``/notify off`` / ``on``     → silence / re-enable
    """
    text = (message.text or "").strip()
    parts = text.split(None, 1)
    arg = parts[1].strip().lower() if len(parts) > 1 else ""

    current = await drafts.get_notifier_interval()
    default = get_settings().notifier_interval_s

    if not arg:
        # No argument → tap-to-pick. The keyboard ✓-marks the current
        # setting; "Default" clears the per-owner override.
        active = current if current is not None else default
        header = (
            "🔕 *Proactive pushes are currently off.*"
            if active == 0
            else f"🔔 *Pushing every {_format_interval(active)}.*"
        )
        if current is None:
            footer = (
                f"_Using the env default ({_format_interval(default)})._\n"
                "Tap a preset below to override:"
            )
        else:
            footer = "Tap a preset below to change:"
        reply = f"{header}\n{footer}"
        try:
            await message.answer(
                tg_normalise(reply),
                parse_mode="Markdown",
                reply_markup=notify_keyboard(current),
            )
        except Exception as exc:
            log.warning("notify.markdown_failed", err=str(exc))
            await message.answer(reply, reply_markup=notify_keyboard(current))
        return

    seconds = _parse_notify_arg(arg, default=default)
    if seconds is None:
        await message.answer(
            "I didn't catch that. Try `/notify 1m`, `/notify 30m`, "
            "`/notify 2h`, or `/notify off`.",
        )
        return

    await drafts.set_notifier_interval(seconds)
    if seconds == 0:
        reply = (
            "🔕 Pushes silenced. Send `/notify on` (or any interval) "
            "to re-enable."
        )
    else:
        reply = (
            f"🔔 OK. Pushing every *{_format_interval(seconds)}* from now on."
        )
    try:
        await message.answer(tg_normalise(reply), parse_mode="Markdown")
    except Exception as exc:
        log.warning("notify.markdown_failed", err=str(exc))
        await message.answer(reply)
    await record(
        "agent",
        "outbound",
        {"text": "notify", "interval_s": seconds},
        session_id=session_id,
    )


@router.callback_query(lambda c: (c.data or "").startswith(CB_NOTIFY_PREFIX))
async def cb_notify(callback: CallbackQuery, session_id: str) -> None:
    """Handle taps on the /notify inline keyboard.

    The callback payload is ``notify:<seconds>`` or ``notify:default``.
    On success we update the persisted override, edit the message in
    place to reflect the new state, and re-render the keyboard so the
    ✓ marker moves to the chosen option.
    """
    data = callback.data or ""
    try:
        chosen = parse_notify_callback(data)
    except ValueError:
        await callback.answer("Stale button — send /notify again.", show_alert=False)
        return

    await drafts.set_notifier_interval(chosen)
    default = get_settings().notifier_interval_s
    active = chosen if chosen is not None else default

    if active == 0:
        ack = "🔕 Silenced."
        body_header = "🔕 *Proactive pushes are off.*"
    else:
        ack = f"🔔 Every {_format_interval(active)}."
        body_header = f"🔔 *Pushing every {_format_interval(active)}.*"
    if chosen is None:
        footer = (
            f"_Using the env default ({_format_interval(default)})._\n"
            "Tap a preset below to override:"
        )
    else:
        footer = "Tap a preset below to change:"
    body = f"{body_header}\n{footer}"

    await callback.answer(ack, show_alert=False)
    # `callback.message` may be a stale ``InaccessibleMessage`` (the
    # original was deleted) — only edit if we have a live ``Message``.
    msg = callback.message
    if not isinstance(msg, Message):
        return
    try:
        await msg.edit_text(
            tg_normalise(body),
            parse_mode="Markdown",
            reply_markup=notify_keyboard(chosen),
        )
    except Exception as exc:
        # Telegram raises if the new content is byte-identical to the
        # current content; we log and move on.
        log.warning("notify.callback_edit_failed", err=str(exc))
    await record(
        "agent",
        "outbound",
        {"text": "notify_via_keyboard", "interval_s": chosen},
        session_id=session_id,
    )


_NOTIFY_MIN_SECONDS = 60
_NOTIFY_MAX_SECONDS = 24 * 3600


def _parse_notify_arg(arg: str, *, default: int) -> int | None:
    """Parse `1m` / `30m` / `2h` / `off` / `on` / number-only into seconds."""
    arg = arg.strip().lower()
    if arg in {"off", "0"}:
        return 0
    if arg in {"on", "default"}:
        return default
    match = _re.fullmatch(r"(\d+)\s*([smhd]?)", arg)
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2) or "s"
    multiplier = {
        "s": 1,
        "m": _SECS_PER_MIN,
        "h": _SECS_PER_HOUR,
        "d": _SECS_PER_DAY,
    }[unit]
    seconds = value * multiplier
    if seconds == 0:
        return 0
    return max(_NOTIFY_MIN_SECONDS, min(seconds, _NOTIFY_MAX_SECONDS))


def _format_interval(seconds: int) -> str:
    """Render seconds as 'N min' / 'N h' for human display."""
    if seconds <= 0:
        return "off"
    if seconds < _SECS_PER_MIN:
        return f"{seconds} s"
    if seconds < _SECS_PER_HOUR:
        return f"{seconds // _SECS_PER_MIN} min"
    if seconds < _SECS_PER_DAY:
        hours = seconds / _SECS_PER_HOUR
        return (
            f"{int(hours)} h"
            if hours == int(hours)
            else f"{round(hours, 1)} h"
        )
    return f"{seconds // _SECS_PER_DAY} d"


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

    # If the previous tap was Edit on a draft, this message is the new copy.
    if await _try_consume_edit(message, session_id, text):
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
    # Persona may write CommonMark **bold**; Telegram classic wants *single*.
    rendered = tg_normalise(reply_text)
    try:
        await message.answer(rendered, parse_mode="Markdown")
    except Exception as exc:
        log.warning("telegram.markdown_render_failed", err=str(exc))
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


async def _try_consume_edit(
    message: Message, session_id: str, text: str
) -> bool:
    """If the chat is awaiting a draft edit, apply this message as new text.

    Returns True if this message was consumed as an edit (caller short-
    circuits and does NOT route through the bridge).
    """
    sess = await sessions.get_by_id(session_id)
    if sess is None:
        return False
    draft_id = sess.state.get("awaiting_edit_draft_id")
    if not isinstance(draft_id, str) or not draft_id:
        return False

    # Clear the FSM flag immediately so a follow-up message routes normally.
    await sessions.merge_state(session_id, {"awaiting_edit_draft_id": None})

    new_text = text.strip()
    if not new_text:
        await message.answer(
            "Empty edit — left the draft as it was. "
            "Tap *📝 Edit* in /inbox to retry.",
            parse_mode="Markdown",
        )
        return True

    draft = await drafts.get(draft_id)
    if draft is None:
        await message.answer("That draft is gone — nothing to update.")
        return True

    # Update the draft payload's caption (or text/body) and re-queue as
    # pending so /inbox picks it up for fresh approval.
    payload = dict(draft.payload) if isinstance(draft.payload, dict) else {}
    field_name = next(
        (k for k in ("caption", "content", "body", "text") if k in payload),
        "caption",
    )
    payload[field_name] = new_text

    conn = await get_connection()
    await conn.execute(
        "UPDATE drafts SET payload = ?, edit_text = ?, status = 'pending', "
        "updated_at = ? WHERE id = ?",
        (
            _json.dumps(payload),
            new_text,
            datetime.now(UTC).isoformat(),
            draft_id,
        ),
    )
    await conn.commit()

    preview = new_text[:400]
    await message.answer(
        f"✅ *Draft updated.* Back in your /inbox waiting for approval.\n\n"
        f"_New copy:_\n{preview}",
        parse_mode="Markdown",
    )
    await record(
        "agent",
        "outbound",
        {"draft_action": "edit:applied", "draft_id": draft_id},
        session_id=session_id,
    )
    return True


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
