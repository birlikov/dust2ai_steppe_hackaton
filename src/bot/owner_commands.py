"""Owner-facing Telegram commands.

Each command pulls live state from the MCP server and asks the
owner-bridge (`claude -p` with the `owner_agent/` persona) to summarise it
in plain English. The owner sees brief prose, never raw JSON.

Slash commands here are conversational shortcuts — the same prose can be
elicited via free text ("anything urgent?", "sales today?") through
:mod:`src.bot.handlers`.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.bot.keyboards import draft_keyboard, parse_draft_callback
from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)
from src.storage import drafts
from src.storage.audit import record

log = get_logger(__name__)
router = Router(name="owner_commands")

DRAFT_CAPTION_PREVIEW = 120  # chars rendered per draft preview line


# ---------------------------------------------------------------------------
# /dashboard
# ---------------------------------------------------------------------------


@router.message(Command("dashboard"))
async def cmd_dashboard(
    message: Message,
    bot: Bot,
    session_id: str,
    owner_bridge: ClaudeBridge,
    mcp: HappycakeMcpClient,
) -> None:
    ack = await message.answer("📊 Looking at the day so far…")
    await bot.send_chat_action(message.chat.id, "typing")
    pos, kitchen, evidence, pending = await asyncio.gather(
        _safe_call(mcp, "square_get_pos_summary"),
        _safe_call(mcp, "kitchen_get_production_summary"),
        _safe_call(mcp, "evaluator_get_evidence_summary"),
        drafts.list_status("pending"),
        return_exceptions=False,
    )
    payload = {
        "pos_summary": pos,
        "kitchen": kitchen,
        "evidence": evidence,
        "pending_drafts": len(pending),
    }
    prose = await _summarise(
        owner_bridge,
        instruction=(
            "Here's the current operational state. Give Askhat (the owner) a "
            "four-bullet brief: today's sales (orders + revenue + channel "
            "mix), kitchen utilisation, drafts pending his approval, and "
            "anything urgent. Lead with the urgent item if any. English, "
            "plain prose, no JSON, no code blocks."
        ),
        payload=payload,
    )
    await _safe_edit(ack, prose)
    await record("agent", "outbound", {"text": "dashboard"}, session_id=session_id)


# ---------------------------------------------------------------------------
# /budget
# ---------------------------------------------------------------------------


@router.message(Command("budget"))
async def cmd_budget(
    message: Message,
    bot: Bot,
    session_id: str,
    owner_bridge: ClaudeBridge,
    mcp: HappycakeMcpClient,
) -> None:
    ack = await message.answer("💰 Reading the marketing state…")
    await bot.send_chat_action(message.chat.id, "typing")
    budget, metrics, marketing_score, leads = await asyncio.gather(
        _safe_call(mcp, "marketing_get_budget"),
        _safe_call(mcp, "marketing_get_campaign_metrics"),
        _safe_call(mcp, "evaluator_score_marketing_loop"),
        drafts.list_recent_leads(limit=5),
        return_exceptions=False,
    )
    payload = {
        "budget_envelope": budget,
        "campaign_metrics": metrics,
        "marketing_score": marketing_score,
        "recent_website_leads": [
            {
                "name": lead.name,
                "intent": lead.intent[:120],
                "utm_source": lead.utm_source,
                "utm_campaign": lead.utm_campaign,
                "created_at": lead.created_at,
            }
            for lead in leads
        ],
    }
    prose = await _summarise(
        owner_bridge,
        instruction=(
            "Marketing snapshot. Give Askhat a brief: budget remaining vs "
            "the $500 envelope, what's working in the campaigns, the most "
            "recent website leads (mention by first name + utm_source), and "
            "one recommended next move. English, four short bullets max."
        ),
        payload=payload,
    )
    await _safe_edit(ack, prose)
    await record("agent", "outbound", {"text": "budget"}, session_id=session_id)


# ---------------------------------------------------------------------------
# /drafts
# ---------------------------------------------------------------------------


@router.message(Command("drafts"))
async def cmd_drafts(message: Message, bot: Bot, session_id: str) -> None:
    await bot.send_chat_action(message.chat.id, "typing")
    pending = await drafts.list_status("pending")
    if not pending:
        await message.answer("Nothing pending. Inbox is clear.")
        await record(
            "agent", "outbound", {"text": "drafts:none"}, session_id=session_id
        )
        return
    await message.answer(f"{len(pending)} draft(s) waiting on you:")
    for draft in pending:
        preview = _short_preview(draft)
        await message.answer(
            preview,
            reply_markup=draft_keyboard(draft.id),
        )
    await record(
        "agent",
        "outbound",
        {"text": "drafts:list", "count": len(pending)},
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# Inline-keyboard callbacks (Approve / Edit / Reject)
# ---------------------------------------------------------------------------


@router.callback_query(lambda c: (c.data or "").startswith("draft:"))
async def cb_draft(
    callback: CallbackQuery,
    bot: Bot,
    session_id: str,
    mcp: HappycakeMcpClient,
) -> None:
    parsed = parse_draft_callback(callback.data or "")
    if parsed is None:
        await callback.answer("Unknown action.")
        return
    action, draft_id = parsed
    draft = await drafts.get(draft_id)
    if draft is None:
        await callback.answer("Draft not found.")
        return

    if action == "approve":
        await _approve_draft(callback, mcp, draft_id, draft)
        await record(
            "agent",
            "outbound",
            {"draft_action": "approve", "draft_id": draft_id},
            session_id=session_id,
        )
    elif action == "reject":
        await drafts.reject(draft_id, "owner rejected via /drafts")
        await callback.answer("Rejected.")
        await _safe_callback_edit(
            callback,
            f"❌ Rejected — {_short_preview(draft, with_header=False)}",
        )
        await record(
            "agent",
            "outbound",
            {"draft_action": "reject", "draft_id": draft_id},
            session_id=session_id,
        )
    elif action == "edit":
        await drafts.edit(draft_id, "(owner requested edit — re-generate)")
        await callback.answer(
            "Edit requested — the next pass regenerates this draft."
        )
        await _safe_callback_edit(
            callback,
            f"📝 Edit requested — {_short_preview(draft, with_header=False)}",
        )
        await record(
            "agent",
            "outbound",
            {"draft_action": "edit", "draft_id": draft_id},
            session_id=session_id,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _approve_draft(
    callback: CallbackQuery,
    mcp: HappycakeMcpClient,
    draft_id: str,
    draft: drafts.Draft,
) -> None:
    await drafts.approve(draft_id)
    publish_note: str | None = None
    if draft.channel == "instagram" and draft.external_id:
        try:
            await call_with_retry(
                mcp,
                "instagram_approve_post",
                {"scheduledPostId": draft.external_id},
            )
            await call_with_retry(
                mcp,
                "instagram_publish_post",
                {"scheduledPostId": draft.external_id},
            )
            await drafts.mark_published(draft_id)
            publish_note = "published to Instagram"
        except (McpTransportError, McpError) as exc:
            publish_note = f"publish failed: {exc}"
            log.error("draft.publish_failed", err=str(exc), draft_id=draft_id)
    await callback.answer("Approved.")
    note = f" — {publish_note}" if publish_note else ""
    await _safe_callback_edit(
        callback,
        f"✅ Approved{note} — {_short_preview(draft, with_header=False)}",
    )


async def _safe_callback_edit(callback: CallbackQuery, text: str) -> None:
    """Edit the callback's source message in place; tolerate missing/old messages."""
    msg = callback.message
    if isinstance(msg, InaccessibleMessage) or msg is None:
        return
    try:
        await msg.edit_text(text)
    except Exception as exc:
        log.warning("callback.edit_failed", err=str(exc))


async def _safe_edit(message: Message, text: str) -> None:
    """Edit a regular message in place; tolerate Telegram quirks."""
    try:
        await message.edit_text(text)
    except Exception as exc:
        log.warning("message.edit_failed", err=str(exc))
        await message.answer(text)


async def _safe_call(mcp: HappycakeMcpClient, tool: str) -> Any:
    """Call an MCP read tool and return its result, or a small error marker."""
    try:
        return await call_with_retry(mcp, tool, {})
    except (McpTransportError, McpError) as exc:
        log.warning("mcp.read_failed", tool=tool, err=str(exc))
        return {"error": str(exc), "tool": tool}


async def _summarise(
    owner_bridge: ClaudeBridge,
    *,
    instruction: str,
    payload: dict[str, Any],
) -> str:
    """Ask the owner-bridge to translate a payload into English prose."""
    try:
        body = (
            f"{instruction}\n\n"
            "Here is the raw data (JSON; do NOT echo it back):\n"
            f"{json.dumps(payload, default=str)[:6000]}"
        )
        reply = await owner_bridge.query(body)
    except ClaudeBridgeError as exc:
        log.error("owner_bridge.query_failed", err=str(exc))
        return (
            "Couldn't reach the assistant just now — try /dashboard again "
            "in a moment."
        )
    return reply.strip() or "(no response)"


def _short_preview(draft: drafts.Draft, *, with_header: bool = True) -> str:
    payload = draft.payload if isinstance(draft.payload, dict) else {}
    group = payload.get("group", draft.kind) or draft.kind
    caption_raw = (
        payload.get("caption")
        or payload.get("content")
        or payload.get("body")
        or payload.get("text")
        or ""
    )
    caption = str(caption_raw).strip().replace("\n", " ")
    if len(caption) > DRAFT_CAPTION_PREVIEW:
        caption = caption[:DRAFT_CAPTION_PREVIEW].rstrip() + "…"
    body = f"{group}: {caption}" if caption else group
    if not with_header:
        return body
    return f"📝 Draft {draft.id[:8]} · {body}"
