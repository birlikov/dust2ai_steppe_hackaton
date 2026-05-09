from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import pytest
from src.agents.claude_bridge import ClaudeBridge
from src.core.config import get_settings
from src.storage import db
from src.workflows.orchestrator import Orchestrator
from src.world.poller import (
    WorldPoller,
    _detect_channel,
    _is_empty,
    _is_finished,
)


@pytest.fixture(autouse=True)
async def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "world_poller_test.db")
    await db.close()
    yield
    await db.close()


class FakeMcpClient:
    """In-memory MCP client returning a queued event sequence."""

    def __init__(self, events: Iterable[Mapping[str, Any]]):
        self._events = list(events)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        raw_text: bool = False,
    ) -> Any:
        self.calls.append((tool, dict(arguments or {})))
        if tool == "world_next_event":
            if self._events:
                return self._events.pop(0)
            return {"status": "finished"}
        # Outbound tool calls always succeed in this fake.
        return {"ok": True}


def _bridge(reply: str = "ok") -> ClaudeBridge:
    async def runner(
        argv: list[str],
        stdin: bytes,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, bytes, bytes]:
        return 0, reply.encode("utf-8"), b""

    return ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/usr/bin/true",
        runner=runner,
    )


@pytest.mark.asyncio
async def test_poller_dispatches_whatsapp_and_calls_send() -> None:
    fake = FakeMcpClient(
        [
            {
                "id": "evt-1",
                "channel": "whatsapp",
                "payload": {
                    "from": "+12815550100",
                    "text": "hi do you have honey today?",
                },
            }
        ]
    )
    orch = Orchestrator(bridge=_bridge('cake "Honey" is on the counter — 1.2 kg, $42.'))
    poller = WorldPoller(
        mcp=fake,  # type: ignore[arg-type]
        orchestrator=orch,
        max_events=1,
        sleeper=_no_sleep,
    )
    result = await poller.run()
    assert result.events_processed == 1
    tools_called = [c[0] for c in fake.calls]
    assert "world_next_event" in tools_called
    assert "whatsapp_send" in tools_called
    args = next(c[1] for c in fake.calls if c[0] == "whatsapp_send")
    assert args["to"] == "+12815550100"
    assert "Honey" in args["message"]


@pytest.mark.asyncio
async def test_poller_dispatches_instagram_dm() -> None:
    fake = FakeMcpClient(
        [
            {
                "id": "evt-2",
                "channel": "instagram_dm",
                "payload": {
                    "threadId": "thread_42",
                    "text": "is the napoleon ready by 5pm?",
                },
            }
        ]
    )
    orch = Orchestrator(bridge=_bridge("yes — by 5 PM."))
    poller = WorldPoller(
        mcp=fake,  # type: ignore[arg-type]
        orchestrator=orch,
        max_events=1,
        sleeper=_no_sleep,
    )
    result = await poller.run()
    assert result.events_processed == 1
    tools_called = [c[0] for c in fake.calls]
    assert "instagram_send_dm" in tools_called


@pytest.mark.asyncio
async def test_poller_dispatches_instagram_comment() -> None:
    fake = FakeMcpClient(
        [
            {
                "id": "evt-3",
                "channel": "instagram_comment",
                "payload": {"commentId": "c123", "text": "love the honey!"},
            }
        ]
    )
    orch = Orchestrator(bridge=_bridge("Thank you, friend."))
    poller = WorldPoller(
        mcp=fake,  # type: ignore[arg-type]
        orchestrator=orch,
        max_events=1,
        sleeper=_no_sleep,
    )
    result = await poller.run()
    assert result.events_processed == 1
    tools_called = [c[0] for c in fake.calls]
    assert "instagram_reply_to_comment" in tools_called


@pytest.mark.asyncio
async def test_poller_logs_unknown_channel_and_continues() -> None:
    fake = FakeMcpClient(
        [
            {"id": "evt-4", "channel": "pos_walkin", "payload": {"order": "x"}},
            {
                "id": "evt-5",
                "channel": "whatsapp",
                "payload": {"from": "+1", "text": "hi"},
            },
        ]
    )
    orch = Orchestrator(bridge=_bridge("hi"))
    poller = WorldPoller(
        mcp=fake,  # type: ignore[arg-type]
        orchestrator=orch,
        max_events=2,
        sleeper=_no_sleep,
    )
    result = await poller.run()
    assert result.events_processed == 2  # both processed; first one logged-only


@pytest.mark.asyncio
async def test_poller_stops_when_scenario_finished() -> None:
    fake = FakeMcpClient([{"status": "finished"}])
    orch = Orchestrator(bridge=_bridge("hi"))
    poller = WorldPoller(
        mcp=fake,  # type: ignore[arg-type]
        orchestrator=orch,
        max_events=10,
        sleeper=_no_sleep,
    )
    result = await poller.run()
    assert result.finished is True
    assert result.events_processed == 0


def test_detect_channel_normalises_aliases() -> None:
    assert _detect_channel({"channel": "WhatsApp"}) == "whatsapp"
    assert _detect_channel({"channel": "Instagram_DM"}) == "instagram_dm"
    assert _detect_channel({"type": "instagram_comment_inbound"}) == "instagram_comment"
    assert _detect_channel({}) == "unknown"


def test_is_empty_true_for_status_empty() -> None:
    assert _is_empty({"status": "empty"}) is True
    assert _is_empty({"status": "no_event"}) is True
    assert _is_empty({}) is True


def test_is_finished_only_on_status_done() -> None:
    assert _is_finished({"status": "finished"}) is True
    assert _is_finished({"status": "running"}) is False
    assert _is_finished(None) is False


async def _no_sleep(_seconds: float) -> None:
    return None
