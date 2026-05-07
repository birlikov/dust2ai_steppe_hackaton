"""aiogram FSM storage backed by our SQLite layer.

Implements aiogram.fsm.storage.base.BaseStorage so /cancel and /restart can
unwind state cleanly across bot restarts.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from aiogram.fsm.state import State
from aiogram.fsm.storage.base import BaseStorage, StorageKey

from src.storage.db import get_connection


class SqliteFsmStorage(BaseStorage):
    """Persists aiogram FSM state in the `fsm_state` table."""

    async def set_state(
        self, key: StorageKey, state: str | State | None = None
    ) -> None:
        value: str | None
        if isinstance(state, State):
            value = state.state
        elif state is None:
            value = None
        else:
            value = str(state)

        conn = await get_connection()
        await conn.execute(
            "INSERT INTO fsm_state(bot_id, chat_id, user_id, state, data) "
            "VALUES (?, ?, ?, ?, '{}') "
            "ON CONFLICT(bot_id, chat_id, user_id) DO UPDATE SET state=excluded.state",
            (key.bot_id, key.chat_id, key.user_id, value),
        )
        await conn.commit()

    async def get_state(self, key: StorageKey) -> str | None:
        conn = await get_connection()
        cur = await conn.execute(
            "SELECT state FROM fsm_state WHERE bot_id=? AND chat_id=? AND user_id=?",
            (key.bot_id, key.chat_id, key.user_id),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        result = row["state"]
        return result if result is None else str(result)

    async def set_data(self, key: StorageKey, data: Mapping[str, Any]) -> None:
        conn = await get_connection()
        await conn.execute(
            "INSERT INTO fsm_state(bot_id, chat_id, user_id, data) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(bot_id, chat_id, user_id) DO UPDATE SET data=excluded.data",
            (key.bot_id, key.chat_id, key.user_id, json.dumps(dict(data))),
        )
        await conn.commit()

    async def get_data(self, key: StorageKey) -> dict[str, Any]:
        conn = await get_connection()
        cur = await conn.execute(
            "SELECT data FROM fsm_state WHERE bot_id=? AND chat_id=? AND user_id=?",
            (key.bot_id, key.chat_id, key.user_id),
        )
        row = await cur.fetchone()
        if row is None:
            return {}
        loaded: dict[str, Any] = json.loads(row["data"]) if row["data"] else {}
        return loaded

    async def close(self) -> None:
        # Connection lifecycle is managed at app shutdown, not per-storage
        return
