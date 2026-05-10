"""Helpers for the /drain_threads owner command.

Extracted here to keep ``owner_commands.py`` under the 500-line ceiling.
All functions are pure utilities (no router registration) so they're safe
to import without triggering aiogram side-effects.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from src.core.logging import get_logger
from src.storage.db import get_connection

log = get_logger(__name__)

_DRAIN_DEDUP_WINDOW_H = 6  # skip threads answered within the last 6 hours


def extract_threads(result: Any) -> list[dict[str, Any]]:
    """Pull the thread list out of whatever shape the MCP tool returned.

    Use when: parsing the result of ``whatsapp_list_threads`` or
    ``instagram_list_dm_threads``.  Tolerates dicts, lists, and error objects.

    Returns:
        A flat list of thread dicts (may be empty).
    """
    if isinstance(result, dict):
        for key in ("threads", "items", "data"):
            val = result.get(key)
            if isinstance(val, list):
                return [t for t in val if isinstance(t, dict)]
    if isinstance(result, list):
        return [t for t in result if isinstance(t, dict)]
    return []


def latest_customer_message(thread: dict[str, Any]) -> str:
    """Extract the most recent inbound customer message text from a thread dict.

    Use when: deciding whether a thread needs a reply.

    Handles several possible shapes the simulator might use:
    - ``messages: [{"role": "user", "text": "…"}, …]``
    - ``lastMessage: {"text": "…"}``
    - ``text`` directly on the thread

    Returns:
        Non-empty string for an unanswered customer message, or ``""`` if
        there's nothing to reply to (already answered, empty, or malformed).
    """
    # Shape 1: messages list — find the last user/customer message.
    messages = thread.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role") or msg.get("from") or "").lower()
            if role in {"user", "customer", "incoming", "inbound"}:
                return str(
                    msg.get("text") or msg.get("body") or msg.get("content") or ""
                ).strip()
    # Shape 2: lastMessage object.
    last = thread.get("lastMessage")
    if isinstance(last, dict):
        role = str(last.get("role") or last.get("from") or "").lower()
        if role not in {"agent", "assistant", "outbound"}:
            return str(last.get("text") or last.get("body") or "").strip()
    # Shape 3: direct text on thread.
    direct = thread.get("text") or thread.get("body") or thread.get("message")
    if direct:
        return str(direct).strip()
    return ""


async def already_answered(thread_id: str) -> bool:
    """Return True if the audit log has an agent outbound for this thread
    within the last ``_DRAIN_DEDUP_WINDOW_H`` hours.

    Use when: deciding whether to skip a thread in /drain_threads.
    Do NOT use: as a replacement for idempotency keys on writes.

    Args:
        thread_id: The platform thread / phone / handle id.

    Returns:
        ``{"status": "ok"}``-style: True if recently answered, False otherwise.
        Never raises — returns False on DB error so the drain continues.
    """
    cutoff = (datetime.now(UTC) - timedelta(hours=_DRAIN_DEDUP_WINDOW_H)).isoformat()
    try:
        conn = await get_connection()
        cur = await conn.execute(
            "SELECT id FROM audit_log "
            "WHERE actor = 'agent' AND event_type = 'outbound' "
            "  AND ts >= ? "
            "  AND payload LIKE ? "
            "LIMIT 1",
            (
                cutoff,
                f'%"external_id": "{thread_id}"%',
            ),
        )
        row = await cur.fetchone()
        return row is not None
    except Exception as exc:
        log.warning("drain.dedup_query_failed", err=str(exc))
        return False
