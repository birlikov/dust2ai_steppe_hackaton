"""Tests for the SqliteFsmStorage adapter."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from aiogram.fsm.storage.base import StorageKey
from src.bot.storage import SqliteFsmStorage
from src.core.config import get_settings
from src.storage import db as db_module


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(tmp_path: Path) -> AsyncIterator[None]:
    os.environ["SQLITE_PATH"] = str(tmp_path / "test.db")
    get_settings.cache_clear()
    await db_module.close()
    try:
        yield
    finally:
        await db_module.close()
        os.environ.pop("SQLITE_PATH", None)
        get_settings.cache_clear()


def _key() -> StorageKey:
    return StorageKey(bot_id=1, chat_id=10, user_id=20)


async def test_state_roundtrip() -> None:
    s = SqliteFsmStorage()
    k = _key()
    assert await s.get_state(k) is None
    await s.set_state(k, "menu")
    assert await s.get_state(k) == "menu"
    await s.set_state(k, None)
    assert await s.get_state(k) is None


async def test_data_roundtrip_and_partial_writes() -> None:
    s = SqliteFsmStorage()
    k = _key()
    assert await s.get_data(k) == {}
    await s.set_data(k, {"step": "greet", "name": "Aida"})
    assert await s.get_data(k) == {"step": "greet", "name": "Aida"}
    await s.set_data(k, {"step": "confirm"})
    assert await s.get_data(k) == {"step": "confirm"}


async def test_state_and_data_are_independent() -> None:
    s = SqliteFsmStorage()
    k = _key()
    await s.set_data(k, {"foo": 1})
    await s.set_state(k, "phase-1")
    assert await s.get_state(k) == "phase-1"
    assert await s.get_data(k) == {"foo": 1}
