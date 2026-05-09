"""Drafts approval-queue repository.

Drafts are the audit trail for everything HappyCake publishes — Instagram posts,
Google Business posts, paid-ads creatives, marketing campaign plans. Each one
goes pending → (approved | edited | rejected) → published. Edited drafts go
back to pending with the owner's edit_text recorded.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from src.storage.db import get_connection

DraftStatus = Literal["pending", "approved", "edited", "rejected", "published"]
ALL_STATUSES: tuple[DraftStatus, ...] = (
    "pending",
    "approved",
    "edited",
    "rejected",
    "published",
)


@dataclass(slots=True)
class Draft:
    id: str
    channel: str
    kind: str
    payload: dict[str, Any]
    status: DraftStatus
    created_at: str
    updated_at: str
    edit_text: str | None = None
    reject_reason: str | None = None
    external_id: str | None = None
    idempotency_key: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def create(
    *,
    channel: str,
    kind: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
) -> Draft:
    """Insert a new pending draft and return it."""
    draft_id = str(uuid.uuid4())
    now = _now()
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO drafts(id, channel, kind, payload, status, "
        "idempotency_key, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)",
        (draft_id, channel, kind, json.dumps(payload), idempotency_key, now, now),
    )
    await conn.commit()
    return Draft(
        id=draft_id,
        channel=channel,
        kind=kind,
        payload=payload,
        status="pending",
        idempotency_key=idempotency_key,
        created_at=now,
        updated_at=now,
    )


async def get(draft_id: str) -> Draft | None:
    conn = await get_connection()
    cur = await conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,))
    row = await cur.fetchone()
    return _row_to_draft(row) if row is not None else None


async def list_status(status: DraftStatus, *, limit: int = 50) -> list[Draft]:
    if status not in ALL_STATUSES:
        raise ValueError(f"unknown status: {status}")
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT * FROM drafts WHERE status = ? ORDER BY created_at DESC LIMIT ?",
        (status, limit),
    )
    rows = await cur.fetchall()
    return [_row_to_draft(r) for r in rows]


async def approve(draft_id: str) -> Draft:
    """Mark a pending draft approved. Caller publishes via the channel API."""
    return await _transition(draft_id, "approved")


async def edit(draft_id: str, edit_text: str) -> Draft:
    """Record the owner's edit and re-queue the draft as pending again."""
    conn = await get_connection()
    now = _now()
    await conn.execute(
        "UPDATE drafts SET status='pending', edit_text=?, updated_at=? "
        "WHERE id=? AND status IN ('pending','approved','rejected')",
        (edit_text, now, draft_id),
    )
    await conn.commit()
    out = await get(draft_id)
    if out is None:
        raise KeyError(draft_id)
    return out


async def reject(draft_id: str, reason: str) -> Draft:
    conn = await get_connection()
    now = _now()
    await conn.execute(
        "UPDATE drafts SET status='rejected', reject_reason=?, updated_at=? WHERE id=?",
        (reason, now, draft_id),
    )
    await conn.commit()
    out = await get(draft_id)
    if out is None:
        raise KeyError(draft_id)
    return out


async def mark_published(draft_id: str, *, external_id: str | None = None) -> Draft:
    conn = await get_connection()
    now = _now()
    await conn.execute(
        "UPDATE drafts SET status='published', external_id=COALESCE(?, external_id), "
        "updated_at=? WHERE id=?",
        (external_id, now, draft_id),
    )
    await conn.commit()
    out = await get(draft_id)
    if out is None:
        raise KeyError(draft_id)
    return out


async def _transition(draft_id: str, status: DraftStatus) -> Draft:
    conn = await get_connection()
    now = _now()
    await conn.execute(
        "UPDATE drafts SET status=?, updated_at=? WHERE id=?",
        (status, now, draft_id),
    )
    await conn.commit()
    out = await get(draft_id)
    if out is None:
        raise KeyError(draft_id)
    return out


def _row_to_draft(row: Any) -> Draft:
    payload_raw = row["payload"]
    payload: dict[str, Any] = json.loads(payload_raw) if payload_raw else {}
    return Draft(
        id=row["id"],
        channel=row["channel"],
        kind=row["kind"],
        payload=payload,
        status=row["status"],
        edit_text=row["edit_text"],
        reject_reason=row["reject_reason"],
        external_id=row["external_id"],
        idempotency_key=row["idempotency_key"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


# ---------------------------------------------------------------------------
# Owner identity (one-row table)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OwnerIdentity:
    telegram_chat_id: int
    telegram_username: str | None
    captured_at: str


async def remember_owner(*, chat_id: int, username: str | None = None) -> None:
    """Idempotently record the owner's Telegram chat id.

    Called from the bot's ``/start`` handler the first time the owner-bot is
    activated. Subsequent calls update the username if it changed but do not
    overwrite the chat id.
    """
    now = _now()
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO owner_identity(id, telegram_chat_id, telegram_username, captured_at) "
        "VALUES (1, ?, ?, ?) "
        "ON CONFLICT(id) DO UPDATE SET telegram_username=excluded.telegram_username",
        (chat_id, username, now),
    )
    await conn.commit()


async def get_owner() -> OwnerIdentity | None:
    conn = await get_connection()
    cur = await conn.execute("SELECT * FROM owner_identity WHERE id = 1")
    row = await cur.fetchone()
    if row is None:
        return None
    return OwnerIdentity(
        telegram_chat_id=row["telegram_chat_id"],
        telegram_username=row["telegram_username"],
        captured_at=row["captured_at"],
    )


# ---------------------------------------------------------------------------
# Leads (one-row-per-form-submission)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Lead:
    id: str
    name: str
    contact: str
    intent: str
    channel_preference: str | None
    utm_source: str | None
    utm_campaign: str | None
    page: str | None
    created_at: str
    reported_to_owner_at: str | None


async def insert_lead(
    *,
    name: str,
    contact: str,
    intent: str,
    channel_preference: str | None = None,
    utm_source: str | None = None,
    utm_campaign: str | None = None,
    page: str | None = None,
) -> Lead:
    lead_id = str(uuid.uuid4())
    now = _now()
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO leads(id, name, contact, intent, channel_preference, "
        "utm_source, utm_campaign, page, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            lead_id,
            name,
            contact,
            intent,
            channel_preference,
            utm_source,
            utm_campaign,
            page,
            now,
        ),
    )
    await conn.commit()
    return Lead(
        id=lead_id,
        name=name,
        contact=contact,
        intent=intent,
        channel_preference=channel_preference,
        utm_source=utm_source,
        utm_campaign=utm_campaign,
        page=page,
        created_at=now,
        reported_to_owner_at=None,
    )


async def mark_lead_reported(lead_id: str) -> None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE leads SET reported_to_owner_at = ? WHERE id = ?",
        (_now(), lead_id),
    )
    await conn.commit()


async def list_recent_leads(limit: int = 50) -> Iterable[Lead]:
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT * FROM leads ORDER BY created_at DESC LIMIT ?", (limit,)
    )
    rows = await cur.fetchall()
    return [
        Lead(
            id=r["id"],
            name=r["name"],
            contact=r["contact"],
            intent=r["intent"],
            channel_preference=r["channel_preference"],
            utm_source=r["utm_source"],
            utm_campaign=r["utm_campaign"],
            page=r["page"],
            created_at=r["created_at"],
            reported_to_owner_at=r["reported_to_owner_at"],
        )
        for r in rows
    ]
