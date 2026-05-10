"""Tests for ``src.channels.poller.ChannelRunner`` — mirrors the FakeMcpClient
pattern from ``test_world_poller.py`` with a tool-name-keyed response map and
a stub orchestrator returning a fixed ``TurnReply``."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from src.channels.poller import ChannelRunner
from src.core.config import get_settings
from src.mcp.http_client import McpTransportError
from src.storage import db as db_module
from src.storage.db import get_connection
from src.workflows.orchestrator import TurnReply, TurnRequest


@pytest_asyncio.fixture(autouse=True)
async def _isolate_db(tmp_path: Path) -> AsyncIterator[None]:
    db_path = tmp_path / "channels_poller_test.db"
    os.environ["SQLITE_PATH"] = str(db_path)
    get_settings.cache_clear()
    await db_module.close()
    try:
        yield
    finally:
        await db_module.close()
        os.environ.pop("SQLITE_PATH", None)
        get_settings.cache_clear()


@dataclass
class FakeMcpClient:
    """In-memory MCP shim. ``responses`` keyed by tool name; ``errors`` selects
    failures so we can flake one channel without touching the others."""

    responses: dict[str, Any] = field(default_factory=dict)
    errors: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)

    async def call(
        self, tool: str, arguments: Mapping[str, Any] | None = None, *, raw_text: bool = False
    ) -> Any:
        self.calls.append((tool, dict(arguments or {})))
        if tool in self.errors:
            raise self.errors[tool]
        return self.responses.get(tool, {"ok": True})


@dataclass
class FakeOrchestrator:
    """Stand-in for ``Orchestrator`` returning a canned reply. ``delay_s`` lets
    the per-thread-lock test simulate slow inference."""

    reply: str = "thanks for reaching out — we're on it."
    delay_s: float = 0.0
    requests: list[TurnRequest] = field(default_factory=list)

    async def run(self, request: TurnRequest) -> TurnReply:
        self.requests.append(request)
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        return TurnReply(
            session_id=f"sess-{request.channel}-{request.external_id}",
            reply=self.reply,
            voice_warnings=[],
        )


async def _no_sleep(_seconds: float) -> None:
    return None


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _wa_thread(text: str, ts: str, *, msg_id: str = "m1") -> dict[str, Any]:
    msg = {"id": msg_id, "from": "+12815550100", "text": text, "createdAt": ts}
    return {"threads": [{"threadId": "wa-1", "fromExternalId": "+12815550100", "messages": [msg]}]}


def _ig_thread(text: str, ts: str, *, thread_id: str = "ig-1") -> dict[str, Any]:
    msg = {"id": "ig-m1", "from": "@aida", "message": text, "createdAt": ts}
    return {"threads": [{"threadId": thread_id, "fromExternalId": "@aida", "messages": [msg]}]}


def _gb_review(text: str, ts: str) -> dict[str, Any]:
    rev = {"id": "rev-9001", "rating": 5, "text": text, "createdAt": ts, "author": "A"}
    return {"reviews": [rev]}


def _empty_lists() -> dict[str, Any]:
    return {
        "whatsapp_list_threads": {"threads": []},
        "instagram_list_dm_threads": {"threads": []},
        "gb_list_pending_reviews": {"reviews": []},
    }


async def _count_idempotency_rows() -> int:
    conn = await get_connection()
    cur = await conn.execute("SELECT COUNT(*) AS n FROM idempotency_keys")
    row = await cur.fetchone()
    assert row is not None
    return int(row["n"])


async def _count_outbound_rows(channel: str) -> int:
    conn = await get_connection()
    cur = await conn.execute("SELECT payload FROM audit_log WHERE event_type = 'outbound'")
    rows = await cur.fetchall()
    return sum(1 for r in rows if json.loads(r["payload"]).get("channel") == channel)


def _make_runner(mcp: FakeMcpClient, orch: FakeOrchestrator) -> ChannelRunner:
    return ChannelRunner(
        mcp=mcp,  # type: ignore[arg-type]
        orchestrator=orch,  # type: ignore[arg-type]
        interval_s=30.0,
        sleeper=_no_sleep,
        inter_outbound_sleep_s=0.0,
    )


@pytest.mark.asyncio
async def test_high_water_skips_pre_existing_inbounds() -> None:
    pre = _iso(datetime.now(UTC) - timedelta(hours=1))
    responses = _empty_lists()
    responses["whatsapp_list_threads"] = _wa_thread("hi", pre, msg_id="m-pre")
    mcp = FakeMcpClient(responses=responses)
    orch = FakeOrchestrator()

    runner = _make_runner(mcp, orch)
    await runner._init_high_water()
    counts = await runner._cycle()

    assert counts == {"whatsapp": 0, "instagram": 0, "gb": 0}
    assert all(c[0] != "whatsapp_send" for c in mcp.calls)
    assert orch.requests == []
    assert await _count_idempotency_rows() == 0


@pytest.mark.asyncio
async def test_new_inbound_triggers_one_outbound() -> None:
    mcp = FakeMcpClient(responses=_empty_lists())
    orch = FakeOrchestrator(reply="hello")
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    mcp.responses["whatsapp_list_threads"] = _wa_thread(
        "do you have honey cake?", new_ts, msg_id="m-new"
    )

    counts = await runner._cycle()

    assert counts["whatsapp"] == 1
    sends = [c for c in mcp.calls if c[0] == "whatsapp_send"]
    assert len(sends) == 1
    assert sends[0][1]["to"] == "+12815550100"
    assert sends[0][1]["message"] == "hello"
    assert await _count_idempotency_rows() == 1
    assert await _count_outbound_rows("whatsapp") == 1


@pytest.mark.asyncio
async def test_idempotency_skips_second_cycle() -> None:
    mcp = FakeMcpClient(responses=_empty_lists())
    orch = FakeOrchestrator(reply="hello")
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    mcp.responses["whatsapp_list_threads"] = _wa_thread(
        "any peanut-free options?", new_ts, msg_id="m-new"
    )

    await runner._cycle()
    await runner._cycle()

    sends = [c for c in mcp.calls if c[0] == "whatsapp_send"]
    assert len(sends) == 1
    assert await _count_idempotency_rows() == 1
    assert await _count_outbound_rows("whatsapp") == 1


@pytest.mark.asyncio
async def test_per_thread_lock_prevents_double_dispatch() -> None:
    mcp = FakeMcpClient(responses=_empty_lists())
    orch = FakeOrchestrator(reply="hello", delay_s=0.5)
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    mcp.responses["whatsapp_list_threads"] = _wa_thread(
        "are you open today?", new_ts, msg_id="m-race"
    )

    a, b = await asyncio.gather(runner._poll_whatsapp(), runner._poll_whatsapp())

    sends = [c for c in mcp.calls if c[0] == "whatsapp_send"]
    assert len(sends) == 1
    assert await _count_idempotency_rows() == 1
    assert {a, b} == {0, 1}


@pytest.mark.asyncio
async def test_channel_failure_isolated() -> None:
    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    responses = _empty_lists()
    responses["instagram_list_dm_threads"] = _ig_thread("is napoleon ready by 5?", new_ts)
    mcp = FakeMcpClient(responses=responses)
    orch = FakeOrchestrator(reply="yes — by 5pm")
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    # Inject the WA transport flake AFTER priming so high-water doesn't fail
    # before the cycle even starts.
    mcp.errors["whatsapp_list_threads"] = McpTransportError("boom")

    counts = await runner._cycle()

    assert counts["whatsapp"] == 0
    assert counts["instagram"] == 1
    ig_sends = [c for c in mcp.calls if c[0] == "instagram_send_dm"]
    assert len(ig_sends) == 1


@pytest.mark.asyncio
async def test_instagram_dm_outbound_uses_thread_id() -> None:
    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    responses = _empty_lists()
    mcp = FakeMcpClient(responses=responses)
    orch = FakeOrchestrator(reply="we close at 8pm")
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    mcp.responses["instagram_list_dm_threads"] = _ig_thread(
        "what time do you close?", new_ts, thread_id="ig-thread-42"
    )
    counts = await runner._cycle()

    assert counts["instagram"] == 1
    sends = [c for c in mcp.calls if c[0] == "instagram_send_dm"]
    assert len(sends) == 1
    args = sends[0][1]
    assert args.get("threadId") == "ig-thread-42"
    assert "@" not in str(args.get("threadId", ""))
    assert args.get("message") == "we close at 8pm"


@pytest.mark.asyncio
async def test_gb_review_uses_review_id() -> None:
    new_ts = _iso(datetime.now(UTC) + timedelta(seconds=5))
    mcp = FakeMcpClient(responses=_empty_lists())
    orch = FakeOrchestrator(reply="thank you, Aida — see you again soon.")
    runner = _make_runner(mcp, orch)
    await runner._init_high_water()

    mcp.responses["gb_list_pending_reviews"] = _gb_review("best napoleon in town!", new_ts)
    counts = await runner._cycle()

    assert counts["gb"] == 1
    replies = [c for c in mcp.calls if c[0] == "gb_simulate_reply"]
    assert len(replies) == 1
    args = replies[0][1]
    assert args.get("reviewId") == "rev-9001"
    assert "threadId" not in args
    reply_value = args.get("reply") or args.get("message") or ""
    assert isinstance(reply_value, str) and reply_value.strip()


@pytest.mark.asyncio
async def test_stop_breaks_run_loop() -> None:
    mcp = FakeMcpClient(responses=_empty_lists())
    orch = FakeOrchestrator()
    runner = _make_runner(mcp, orch)

    async def _stop_after_first_tick(_seconds: float) -> None:
        runner.stop()

    runner.sleeper = _stop_after_first_tick

    await asyncio.wait_for(runner.run(), timeout=1.0)
