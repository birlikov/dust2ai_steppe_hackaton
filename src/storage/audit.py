"""Append-only audit log — every inbound, tool call, tool result, outbound, error."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from src.storage.db import get_connection

Actor = Literal["user", "agent", "tool", "system"]
EventType = Literal[
    "inbound", "outbound", "tool_call", "tool_result", "error", "note"
]


@dataclass(slots=True)
class AuditEvent:
    id: int
    ts: str
    session_id: str | None
    workflow_id: str | None
    actor: Actor
    event_type: EventType
    payload: dict[str, Any]


async def record(
    actor: Actor,
    event_type: EventType,
    payload: dict[str, Any],
    *,
    session_id: str | None = None,
    workflow_id: str | None = None,
) -> None:
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO audit_log(ts, session_id, workflow_id, actor, event_type, payload) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            datetime.now(UTC).isoformat(),
            session_id,
            workflow_id,
            actor,
            event_type,
            json.dumps(payload),
        ),
    )
    await conn.commit()


async def list_for_session(session_id: str, limit: int = 200) -> Iterable[AuditEvent]:
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT * FROM audit_log WHERE session_id = ? ORDER BY id ASC LIMIT ?",
        (session_id, limit),
    )
    rows = await cur.fetchall()
    return [
        AuditEvent(
            id=r["id"],
            ts=r["ts"],
            session_id=r["session_id"],
            workflow_id=r["workflow_id"],
            actor=r["actor"],
            event_type=r["event_type"],
            payload=json.loads(r["payload"]),
        )
        for r in rows
    ]
