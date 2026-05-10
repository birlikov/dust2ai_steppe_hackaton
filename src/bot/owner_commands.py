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
from datetime import UTC, datetime, timedelta
from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.bot.keyboards import draft_keyboard, parse_draft_callback
from src.bot.markdown import tg_normalise
from src.core.logging import get_logger
from src.mcp.http_client import (
    HappycakeMcpClient,
    McpError,
    McpTransportError,
    call_with_retry,
)
from src.storage import drafts, sessions
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
    (
        pos,
        kitchen,
        kitchen_tickets,
        evidence,
        gb_metrics,
        wa_threads,
        ig_threads,
        sales_history,
        scenario_summary,
        pending,
    ) = await asyncio.gather(
        _safe_call(mcp, "square_get_pos_summary"),
        _safe_call(mcp, "kitchen_get_production_summary"),
        _safe_call(mcp, "kitchen_list_tickets"),
        _safe_call(mcp, "evaluator_get_evidence_summary"),
        _safe_call(mcp, "gb_get_metrics"),
        _safe_call(mcp, "whatsapp_list_threads"),
        _safe_call(mcp, "instagram_list_dm_threads"),
        _safe_call(mcp, "marketing_get_sales_history"),
        _safe_call(mcp, "world_get_scenario_summary"),
        drafts.list_status("pending"),
        return_exceptions=False,
    )
    payload = {
        "pos_summary": pos,
        "kitchen": kitchen,
        "kitchen_tickets": kitchen_tickets,
        "evidence": evidence,
        "gb_metrics": gb_metrics,
        "live_threads": {
            "whatsapp": wa_threads,
            "instagram": ig_threads,
        },
        "sales_history": sales_history,
        "scenario_summary": scenario_summary,
        "pending_drafts": len(pending),
    }
    prose = await _summarise(
        owner_bridge,
        instruction=(
            "Here's the current operational state. Give Askhat (the owner) a "
            "five-bullet brief covering: today's sales (orders + revenue + "
            "channel mix), kitchen tickets in flight + production headroom, "
            "live conversations (WA/IG thread counts), Google Business "
            "review pulse (count + avg rating + response rate), and drafts "
            "pending his approval. Lead with the urgent item if any. English, "
            "plain prose, no JSON, no code blocks."
        ),
        payload=payload,
    )
    await _safe_edit(ack, tg_normalise(prose))
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
    (
        budget,
        metrics,
        marketing_score,
        sales_history,
        margin_map_raw,
        leads,
    ) = await asyncio.gather(
        _safe_call(mcp, "marketing_get_budget"),
        _safe_call(mcp, "marketing_get_campaign_metrics"),
        _safe_call(mcp, "evaluator_score_marketing_loop"),
        _safe_call(mcp, "marketing_get_sales_history"),
        _safe_call(mcp, "marketing_get_margin_by_product"),
        drafts.list_recent_leads(limit=8),
        return_exceptions=False,
    )
    # Compute a priority_score per lead — margin x source-weight x recency.
    # Pure client-side: no schema change to the leads table.
    margin_avg = _avg_margin(margin_map_raw)
    scored: list[dict[str, Any]] = [
        {
            "name": lead.name,
            "intent": lead.intent[:120],
            "utm_source": lead.utm_source,
            "utm_campaign": lead.utm_campaign,
            "created_at": lead.created_at,
            "priority_score": _lead_priority_score(
                margin_avg=margin_avg,
                utm_source=lead.utm_source,
                created_at=lead.created_at,
            ),
        }
        for lead in leads
    ]
    scored.sort(key=lambda d: int(d["priority_score"]), reverse=True)
    payload = {
        "budget_envelope": budget,
        "campaign_metrics": metrics,
        "marketing_score": marketing_score,
        "sales_history": sales_history,
        "avg_margin_pct": round(margin_avg * 100, 1),
        "leads_by_priority": scored[:3],
        "all_recent_leads": scored,
    }
    prose = await _summarise(
        owner_bridge,
        instruction=(
            "Marketing snapshot. Give Askhat a brief: budget remaining vs "
            "the $500 envelope, what's working in the campaigns, the **top "
            "three leads by priority_score** (mention each by first name + "
            "utm_source, in order), and one recommended next move. English, "
            "four short bullets max."
        ),
        payload=payload,
    )
    await _safe_edit(ack, tg_normalise(prose))
    await record("agent", "outbound", {"text": "budget"}, session_id=session_id)


# ---------------------------------------------------------------------------
# /inbox
# ---------------------------------------------------------------------------


@router.message(Command("inbox", "drafts"))
async def cmd_inbox(message: Message, bot: Bot, session_id: str) -> None:
    """List everything waiting on the owner. Aliases: /inbox (canonical), /drafts (legacy)."""
    await bot.send_chat_action(message.chat.id, "typing")
    pending = await drafts.list_status("pending")
    if not pending:
        await message.answer(
            "📭 *Inbox clear.* No marketing posts waiting on you.\n\n"
            "_Customer orders confirm automatically — they don't queue here._",
            parse_mode="Markdown",
        )
        await record(
            "agent", "outbound", {"text": "inbox:empty"}, session_id=session_id
        )
        return
    intro = f"📥 *{len(pending)} item(s)* waiting for your call:"
    await message.answer(intro, parse_mode="Markdown")
    for draft in pending:
        preview = _short_preview(draft)
        try:
            await message.answer(
                preview,
                reply_markup=draft_keyboard(draft.id),
                parse_mode="Markdown",
            )
        except Exception as exc:
            log.warning("inbox.preview_markdown_failed", err=str(exc))
            await message.answer(preview, reply_markup=draft_keyboard(draft.id))
    await record(
        "agent",
        "outbound",
        {"text": "inbox:list", "count": len(pending)},
        session_id=session_id,
    )


# ---------------------------------------------------------------------------
# /refund <order_id> — owner-initiated refund flow with approval gate
# ---------------------------------------------------------------------------


@router.message(Command("refund"))
async def cmd_refund(
    message: Message,
    bot: Bot,
    session_id: str,
    owner_bridge: ClaudeBridge,
    mcp: HappycakeMcpClient,
) -> None:
    """``/refund <order_id> [reason …]`` — queue a refund offer in /inbox.

    Looks up the order via ``square_recent_orders``, asks the owner-bridge
    to draft a brand-voice apology + refund line, and writes a
    ``refund_offer`` draft. On Approve in ``/inbox`` we call
    ``square_update_order_status`` with ``cancelled`` + a refund note.
    """
    text = (message.text or "").strip()
    parts = text.split(maxsplit=2)
    expected_min_parts = 2
    expected_with_reason = 3
    if len(parts) < expected_min_parts:
        await message.answer(
            "Usage: `/refund <order_id> [reason]`\n"
            "Example: `/refund sq_order_1778… overcharged for the slice`",
            parse_mode="Markdown",
        )
        return
    order_id = parts[1].strip()
    reason = parts[2].strip() if len(parts) >= expected_with_reason else ""

    ack = await message.answer(
        f"💸 Drafting a refund offer for `{order_id}`…",
        parse_mode="Markdown",
    )
    await bot.send_chat_action(message.chat.id, "typing")

    # Pull the order so the persona has real numbers to reference.
    order = await _lookup_order(mcp, order_id)
    if order is None:
        await _safe_edit(
            ack,
            f"❌ I can't find order `{order_id}` in the recent ledger. "
            f"Double-check the id from /dashboard or square_recent_orders.",
        )
        return

    payload_for_bridge: dict[str, Any] = {
        "order": order,
        "owner_reason": reason or "(none provided)",
    }
    instruction = (
        "The owner has decided to refund this order. Write a one-paragraph "
        "customer-facing apology + refund-offer in HappyCake voice. Plain "
        "English, no JSON, no asterisks, ≤4 sentences. Mention the cake by "
        "the brand-voice form (e.g. cake \"Honey\" — slice). Acknowledge the "
        "issue without being defensive. Do not state a refund amount unless "
        "the owner specified one in their reason."
    )
    try:
        copy = await _summarise(
            owner_bridge,
            instruction=instruction,
            payload=payload_for_bridge,
        )
    except ClaudeBridgeError as exc:
        await _safe_edit(
            ack, f"⚠️ Couldn't draft the refund text: {exc}. Try again?"
        )
        return

    draft = await drafts.create(
        channel="customer",
        kind="refund_offer",
        payload={
            "order_id": order_id,
            "reason": reason,
            "copy": copy,
            "order_snapshot": order,
        },
        idempotency_key=f"refund:{order_id}",
    )
    await _safe_edit(
        ack,
        "💸 *Refund draft queued in /inbox.*\n"
        "Tap **✅ Approve** to process the refund (calls "
        "`square_update_order_status` with status=`cancelled`).\n\n"
        f"_Draft preview:_\n{copy[:400]}",
    )
    # Surface the draft inline for one-tap approval.
    try:
        await message.answer(
            _short_preview(draft, with_header=True),
            reply_markup=draft_keyboard(draft.id),
            parse_mode="Markdown",
        )
    except Exception as exc:
        log.warning("refund.preview_failed", err=str(exc))
    await record(
        "agent",
        "outbound",
        {"text": "refund:drafted", "order_id": order_id, "draft_id": draft.id},
        session_id=session_id,
    )


async def _lookup_order(
    mcp: HappycakeMcpClient, order_id: str
) -> dict[str, Any] | None:
    """Find ``order_id`` in the most recent simulator orders. Returns None
    if absent or the call fails."""
    try:
        result = await call_with_retry(
            mcp, "square_recent_orders", {"limit": 50}
        )
    except (McpTransportError, McpError) as exc:
        log.warning("refund.lookup_failed", err=str(exc))
        return None
    orders = []
    if isinstance(result, dict):
        raw = result.get("orders")
        if isinstance(raw, list):
            orders = [o for o in raw if isinstance(o, dict)]
    for order in orders:
        if str(order.get("id") or order.get("orderId") or "") == order_id:
            return order
    return None


# ---------------------------------------------------------------------------
# /wire-webhooks — register Meta WhatsApp + Instagram webhooks at the
# current ngrok URL. One-shot helper; rarely needed in dev (we drive
# events through world_next_event), useful when an evaluator wants to
# wire a real Meta sandbox to the running tunnel.
# ---------------------------------------------------------------------------


@router.message(Command("wire_webhooks"))
async def cmd_wire_webhooks(
    message: Message,
    bot: Bot,
    session_id: str,
    mcp: HappycakeMcpClient,
) -> None:
    """``/wire_webhooks <https://your-tunnel/webhook/whatsapp>`` — register
    the Meta-shaped webhook URL with the simulator so injected
    WhatsApp + Instagram events round-trip through the storefront.
    """
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    expected_min_parts = 2
    if len(parts) < expected_min_parts or not parts[1].startswith("https://"):
        await message.answer(
            "Usage: `/wire_webhooks <https://…ngrok…/webhook/whatsapp>`\n"
            "I'll derive the matching `/webhook/instagram` URL from it.",
            parse_mode="Markdown",
        )
        return
    wa_url = parts[1].strip().rstrip("/")
    ig_url = wa_url.replace("/webhook/whatsapp", "/webhook/instagram")
    ack = await message.answer("🔗 Registering webhooks with the simulator…")
    results: list[str] = []
    for tool, url in (
        ("whatsapp_register_webhook", wa_url),
        ("instagram_register_webhook", ig_url),
    ):
        try:
            await call_with_retry(mcp, tool, {"url": url})
            results.append(f"✓ {tool} → {url}")
        except (McpTransportError, McpError) as exc:
            results.append(f"✗ {tool}: {exc}")
            log.warning("wire_webhooks.failed", tool=tool, err=str(exc))
    await _safe_edit(ack, "\n".join(results))
    await record(
        "agent",
        "outbound",
        {"text": "wire_webhooks", "wa_url": wa_url, "ig_url": ig_url},
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
        await drafts.reject(draft_id, "owner rejected via /inbox")
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
        # Park the chat in "awaiting edit" mode. The next message handler
        # in src/bot/handlers.py picks the new text up and updates the
        # draft, then re-enables the chat for normal use.
        await sessions.merge_state(
            session_id, {"awaiting_edit_draft_id": draft_id}
        )
        await callback.answer("Send your replacement text as the next message.")
        await _safe_callback_edit(
            callback,
            f"📝 *Editing draft.* Send the new text in the next message.\n\n"
            f"_Current copy:_\n{_short_preview(draft, with_header=False)}",
        )
        await record(
            "agent",
            "outbound",
            {"draft_action": "edit:start", "draft_id": draft_id},
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
    elif draft.kind == "refund_offer":
        order_id = str(draft.payload.get("order_id") or "") if isinstance(
            draft.payload, dict
        ) else ""
        if order_id:
            try:
                await call_with_retry(
                    mcp,
                    "square_update_order_status",
                    {
                        "orderId": order_id,
                        "status": "cancelled",
                        "note": "refund approved by owner",
                    },
                )
                await drafts.mark_published(draft_id)
                publish_note = f"refunded order {order_id[:14]}"
            except (McpTransportError, McpError) as exc:
                publish_note = f"refund failed: {exc}"
                log.error(
                    "refund.update_failed", err=str(exc), draft_id=draft_id
                )
        else:
            publish_note = "no order_id on draft — refund skipped"
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
    rendered = tg_normalise(text)
    try:
        await msg.edit_text(rendered, parse_mode="Markdown")
    except Exception as exc:
        log.warning("callback.edit_failed", err=str(exc))
        try:
            await msg.edit_text(text)
        except Exception as exc2:
            log.warning("callback.edit_plain_failed", err=str(exc2))


async def _safe_edit(message: Message, text: str) -> None:
    """Edit a regular message in place; tolerate Telegram quirks."""
    rendered = tg_normalise(text)
    try:
        await message.edit_text(rendered, parse_mode="Markdown")
    except Exception as exc:
        log.warning("message.edit_failed_md", err=str(exc))
        try:
            await message.edit_text(text)
        except Exception as exc2:
            log.warning("message.edit_failed_plain", err=str(exc2))
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


# ---------------------------------------------------------------------------
# Lead priority scoring (powered by ``marketing_get_margin_by_product``)
# ---------------------------------------------------------------------------

# Per-source heuristic weights — higher = more likely to convert into a
# real order. Tuned roughly to industry benchmarks for a small bakery
# (Google local search > Instagram > paid social > unknown).
_SOURCE_WEIGHTS: dict[str, float] = {
    "google": 1.0,
    "google-search": 1.0,
    "google-local": 1.0,
    "instagram": 0.8,
    "ig": 0.8,
    "meta": 0.7,
    "facebook": 0.65,
    "fb": 0.65,
    "whatsapp": 0.85,
    "wa": 0.85,
    "referral": 0.95,
    "direct": 0.55,
    "": 0.5,
}


def _avg_margin(raw: Any) -> float:
    """Pick a representative margin (0..1) from ``marketing_get_margin_by_product``.

    Falls back to 0.4 (a sensible baseline for the bakery's gross margin)
    when the call missed or the response is malformed — we only need a
    relative scoring weight, not a dollar number.
    """
    try:
        if isinstance(raw, dict):
            items = raw.get("items") or raw.get("products") or []
            margins: list[float] = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                m = item.get("marginPct") or item.get("margin_pct") or item.get("margin")
                if m is None:
                    continue
                m_f = float(m)
                if m_f > 1:
                    m_f = m_f / 100.0
                if 0 <= m_f <= 1:
                    margins.append(m_f)
            if margins:
                return sum(margins) / len(margins)
    except (TypeError, ValueError):
        pass
    return 0.4


def _lead_priority_score(
    *,
    margin_avg: float,
    utm_source: str | None,
    created_at: str | None,
) -> int:
    """Return a 0-100 integer score = ``margin x source_weight x recency``.

    Recency decays linearly across 7 days: same-day = 1.0, week-old = 0.0.
    """
    src_key = (utm_source or "").strip().lower()
    src_weight = _SOURCE_WEIGHTS.get(src_key, 0.5)

    recency = 0.5  # default if we can't parse the timestamp
    if created_at:
        try:
            ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            delta = datetime.now(UTC) - ts
            seven_days = timedelta(days=7)
            ratio = max(0.0, 1.0 - delta / seven_days)
            recency = ratio
        except (ValueError, TypeError):
            recency = 0.5

    raw = margin_avg * src_weight * recency
    # margin_avg is ≤1, src_weight is ≤1, recency is ≤1 — so raw is ≤1.
    # Map to 0-100 for an at-a-glance score.
    return round(raw * 100)


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
