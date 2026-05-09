"""Owner-facing Telegram commands: dashboard, budget, drafts queue.

These commands surface MCP-derived state to the business owner and let them
approve / edit / reject queued drafts (Instagram posts, Google Business posts,
paid-ads creatives). The handlers depend on the MCP HTTP client and the drafts
repository — both injected from :mod:`src.bot.app` via aiogram's data dict.
"""

from __future__ import annotations

import json
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

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

DRAFT_PREVIEW_MAX = 800


@router.message(Command("dashboard"))
async def cmd_dashboard(
    message: Message,
    session_id: str,
    mcp: HappycakeMcpClient,
) -> None:
    parts: list[str] = ["📊 *HappyCake dashboard*"]
    parts.append(await _summary_block("Sales (POS)", mcp, "square_get_pos_summary"))
    parts.append(
        await _summary_block(
            "Kitchen", mcp, "kitchen_get_production_summary"
        )
    )
    parts.append(
        await _summary_block(
            "Evaluator evidence", mcp, "evaluator_get_evidence_summary"
        )
    )
    text = "\n\n".join(parts)
    await message.answer(text, parse_mode="Markdown")
    await record("agent", "outbound", {"text": "dashboard"}, session_id=session_id)


@router.message(Command("budget"))
async def cmd_budget(
    message: Message,
    session_id: str,
    mcp: HappycakeMcpClient,
) -> None:
    blocks = ["💰 *Marketing budget*"]
    blocks.append(await _summary_block("Budget envelope", mcp, "marketing_get_budget"))
    blocks.append(
        await _summary_block(
            "Recent campaign metrics", mcp, "marketing_get_campaign_metrics"
        )
    )
    leads = list(await drafts.list_recent_leads(limit=5))
    if leads:
        recent = "\n".join(
            f"  • {lead.created_at[:10]} {lead.name} — {lead.intent[:60]}"
            f" (utm={lead.utm_source or 'direct'}/{lead.utm_campaign or '-'})"
            for lead in leads
        )
        blocks.append("*Recent website leads*\n" + recent)
    await message.answer("\n\n".join(blocks), parse_mode="Markdown")
    await record("agent", "outbound", {"text": "budget"}, session_id=session_id)


@router.message(Command("drafts"))
async def cmd_drafts(message: Message, session_id: str) -> None:
    pending = await drafts.list_status("pending")
    if not pending:
        await message.answer("No drafts pending. ✨")
        await record(
            "agent", "outbound", {"text": "drafts:none"}, session_id=session_id
        )
        return
    await message.answer(f"{len(pending)} draft(s) waiting on you:")
    for draft in pending:
        preview = _format_draft(draft)
        await message.answer(
            preview,
            parse_mode="Markdown",
            reply_markup=draft_keyboard(draft.id),
        )
    await record(
        "agent",
        "outbound",
        {"text": "drafts:list", "count": len(pending)},
        session_id=session_id,
    )


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
        await _safe_edit(
            callback,
            f"❌ *Rejected*\n\n{_format_draft_body(draft)}",
        )
        await record(
            "agent",
            "outbound",
            {"draft_action": "reject", "draft_id": draft_id},
            session_id=session_id,
        )
    elif action == "edit":
        # Lightweight edit: mark the draft so the owner knows we received the
        # tap; full edit-text capture is a v2 feature (would need an FSM).
        await drafts.edit(draft_id, "(owner requested edit — re-generate)")
        await callback.answer(
            "Edit requested — the next pass will regenerate this draft."
        )
        await _safe_edit(
            callback,
            f"📝 *Edit requested*\n\n{_format_draft_body(draft)}",
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
            publish_note = " — published to Instagram."
        except (McpTransportError, McpError) as exc:
            publish_note = f" — publish failed: {exc}"
            log.error("draft.publish_failed", err=str(exc), draft_id=draft_id)
    await callback.answer("Approved.")
    await _safe_edit(
        callback,
        f"✅ *Approved*{publish_note or ''}\n\n{_format_draft_body(draft)}",
    )


async def _safe_edit(callback: CallbackQuery, text: str) -> None:
    """Edit the message body in place, tolerating Telegram's optional types."""
    msg = callback.message
    if msg is None or isinstance(msg, InaccessibleMessage):
        return
    await msg.edit_text(text, parse_mode="Markdown")


async def _summary_block(label: str, mcp: HappycakeMcpClient, tool: str) -> str:
    try:
        data = await call_with_retry(mcp, tool, {})
    except (McpTransportError, McpError) as exc:
        return f"*{label}*\n_unable to fetch ({exc})_"
    return f"*{label}*\n```\n{_pretty(data)}\n```"


def _pretty(value: Any) -> str:
    """Compact JSON pretty-print, capped at 1500 chars to stay under TG 4096."""
    try:
        text = json.dumps(value, ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        text = str(value)
    return text[:1500]


def _format_draft(draft: drafts.Draft) -> str:
    body = _format_draft_body(draft)
    head = (
        f"📝 *Draft* `{draft.id[:8]}` — {draft.channel}/{draft.kind}"
        f" — created {draft.created_at[:19]}"
    )
    return f"{head}\n\n{body}"


def _format_draft_body(draft: drafts.Draft) -> str:
    payload = draft.payload
    fields: list[str] = []
    for key in ("caption", "content", "body", "text", "imageUrl", "scheduledFor"):
        v = payload.get(key)
        if v:
            fields.append(f"*{key}*: {str(v)[:600]}")
    if not fields:
        fields = [f"```\n{_pretty(payload)}\n```"]
    if draft.edit_text:
        fields.append(f"\n_owner edit:_ {draft.edit_text}")
    return "\n".join(fields)
