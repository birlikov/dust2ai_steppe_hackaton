"""Conversation session repository — channel-agnostic state per (channel, external_id)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from src.storage.db import get_connection


@dataclass(slots=True)
class Session:
    id: str
    channel: str
    external_id: str
    workflow_id: str | None
    state: dict[str, Any]
    created_at: str
    updated_at: str


def _now() -> str:
    return datetime.now(UTC).isoformat()


async def get_or_create(channel: str, external_id: str) -> Session:
    """Find an existing session for (channel, external_id) or create a new one."""
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT * FROM sessions WHERE channel = ? AND external_id = ?",
        (channel, external_id),
    )
    row = await cur.fetchone()
    if row is not None:
        return _row_to_session(row)

    sid = str(uuid.uuid4())
    now = _now()
    await conn.execute(
        "INSERT INTO sessions(id, channel, external_id, workflow_id, state, "
        "created_at, updated_at) VALUES (?, ?, ?, NULL, '{}', ?, ?)",
        (sid, channel, external_id, now, now),
    )
    await conn.commit()
    return Session(
        id=sid,
        channel=channel,
        external_id=external_id,
        workflow_id=None,
        state={},
        created_at=now,
        updated_at=now,
    )


async def update_state(session_id: str, state: dict[str, Any]) -> None:
    """Replace session state. Use merge_state to patch instead."""
    conn = await get_connection()
    await conn.execute(
        "UPDATE sessions SET state = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state), _now(), session_id),
    )
    await conn.commit()


async def merge_state(session_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    """Shallow-merge patch into session state. Returns the new state."""
    conn = await get_connection()
    cur = await conn.execute("SELECT state FROM sessions WHERE id = ?", (session_id,))
    row = await cur.fetchone()
    if row is None:
        raise KeyError(session_id)
    state: dict[str, Any] = json.loads(row["state"])
    state.update(patch)
    await conn.execute(
        "UPDATE sessions SET state = ?, updated_at = ? WHERE id = ?",
        (json.dumps(state), _now(), session_id),
    )
    await conn.commit()
    return state


async def set_workflow(session_id: str, workflow_id: str | None) -> None:
    conn = await get_connection()
    await conn.execute(
        "UPDATE sessions SET workflow_id = ?, updated_at = ? WHERE id = ?",
        (workflow_id, _now(), session_id),
    )
    await conn.commit()


def _row_to_session(row: Any) -> Session:
    return Session(
        id=row["id"],
        channel=row["channel"],
        external_id=row["external_id"],
        workflow_id=row["workflow_id"],
        state=json.loads(row["state"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
