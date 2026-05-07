"""Idempotency-key cache — repeats of the same key return the cached result."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from src.storage.db import get_connection


def _now() -> datetime:
    return datetime.now(UTC)


async def get(key: str) -> dict[str, Any] | None:
    """Return the cached result for key if present and not expired, else None."""
    conn = await get_connection()
    cur = await conn.execute(
        "SELECT result, expires_at FROM idempotency_keys WHERE key = ?", (key,)
    )
    row = await cur.fetchone()
    if row is None:
        return None
    if row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= _now():
        return None
    result: dict[str, Any] = json.loads(row["result"])
    return result


async def put(
    key: str,
    scope: str,
    result: dict[str, Any],
    ttl_seconds: int | None = 86400,
) -> None:
    """Cache `result` under `key`. Default TTL: 24h."""
    conn = await get_connection()
    expires = (_now() + timedelta(seconds=ttl_seconds)).isoformat() if ttl_seconds else None
    await conn.execute(
        "INSERT OR REPLACE INTO idempotency_keys(key, scope, result, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (key, scope, json.dumps(result), _now().isoformat(), expires),
    )
    await conn.commit()
