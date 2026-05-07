"""Storage layer unit tests using a fresh SQLite file per test."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from src.core.config import get_settings
from src.storage import db as db_module
from src.storage.audit import list_for_session, record
from src.storage.idempotency import get, put
from src.storage.sessions import get_or_create, merge_state


@pytest_asyncio.fixture(autouse=True)
async def _isolated_db(tmp_path: Path) -> AsyncIterator[None]:
    db_path = tmp_path / "test.db"
    os.environ["SQLITE_PATH"] = str(db_path)
    get_settings.cache_clear()
    await db_module.close()
    try:
        yield
    finally:
        await db_module.close()
        os.environ.pop("SQLITE_PATH", None)
        get_settings.cache_clear()


async def test_session_get_or_create_is_stable() -> None:
    a = await get_or_create("telegram", "12345")
    b = await get_or_create("telegram", "12345")
    assert a.id == b.id
    assert a.channel == "telegram"


async def test_session_merge_state_is_shallow() -> None:
    s = await get_or_create("whatsapp", "+15551234567")
    new_state = await merge_state(s.id, {"step": "greet", "name": "Aida"})
    assert new_state == {"step": "greet", "name": "Aida"}
    new_state = await merge_state(s.id, {"step": "confirm"})
    assert new_state == {"step": "confirm", "name": "Aida"}


async def test_idempotency_get_returns_none_when_absent() -> None:
    assert await get("missing-key") is None


async def test_idempotency_roundtrip() -> None:
    await put("k1", scope="test", result={"status": "ok", "n": 1})
    cached = await get("k1")
    assert cached == {"status": "ok", "n": 1}


async def test_audit_log_records_and_reads() -> None:
    s = await get_or_create("telegram", "audit-1")
    await record("user", "inbound", {"text": "hi"}, session_id=s.id)
    await record("agent", "outbound", {"text": "hello"}, session_id=s.id)
    events = list(await list_for_session(s.id))
    assert len(events) == 2
    assert events[0].event_type == "inbound"
    assert events[1].payload == {"text": "hello"}
