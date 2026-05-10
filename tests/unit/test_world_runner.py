"""Tests for the always-on :class:`WorldRunner` supervisor."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from src.agents.claude_bridge import ClaudeBridge
from src.core.config import get_settings
from src.storage import db
from src.workflows.orchestrator import Orchestrator
from src.world import runner as runner_mod
from src.world.runner import WorldRunner


@pytest.fixture(autouse=True)
async def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "world_runner_test.db")
    await db.close()
    yield
    await db.close()


class _Mcp:
    """Minimal MCP fake. Returns one WA event then 'finished' forever."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._delivered = False

    async def call(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        raw_text: bool = False,
    ) -> Any:
        self.calls.append((tool, dict(arguments or {})))
        if tool == "world_next_event":
            if not self._delivered:
                self._delivered = True
                return {
                    "channel": "whatsapp",
                    "payload": {"text": "hi", "from": "+15551234567"},
                }
            return {"status": "finished"}
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
async def test_runner_drains_one_event_then_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The runner should drain pending events through the orchestrator
    and exit cleanly when ``stop()`` is called."""
    mcp = _Mcp()
    orch = Orchestrator(bridge=_bridge("yes ma'am"))
    runner = WorldRunner(mcp=mcp, orchestrator=orch)

    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        # First sleep: signal stop so the supervisor exits its loop.
        runner.stop()

    runner.sleeper = _sleep
    # Make the inner poller's empty/error backoffs zero too.
    monkeypatch.setattr(runner_mod, "MIN_RESTART_BACKOFF_S", 0.0)
    monkeypatch.setattr(runner_mod, "MAX_RESTART_BACKOFF_S", 0.0)

    await runner.run()

    tools_called = [t for t, _ in mcp.calls]
    assert "world_next_event" in tools_called
    assert "whatsapp_send" in tools_called
    # Supervisor should have looped at least once and slept once.
    assert sleeps, "supervisor never reached the restart-sleep branch"


@pytest.mark.asyncio
async def test_runner_stops_cleanly_when_no_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle MCP (always returns finished) should not hot-loop —
    stop() must break the supervisor out promptly."""

    class _IdleMcp:
        async def call(
            self,
            tool: str,
            arguments: Mapping[str, Any] | None = None,
            *,
            raw_text: bool = False,
        ) -> Any:
            return {"status": "finished"}

    mcp = _IdleMcp()
    runner = WorldRunner(mcp=mcp, orchestrator=Orchestrator(bridge=_bridge()))

    iterations = {"n": 0}

    async def _sleep(seconds: float) -> None:
        iterations["n"] += 1
        if iterations["n"] >= 2:
            runner.stop()

    runner.sleeper = _sleep
    monkeypatch.setattr(runner_mod, "MIN_RESTART_BACKOFF_S", 0.0)
    monkeypatch.setattr(runner_mod, "MAX_RESTART_BACKOFF_S", 0.0)

    await runner.run()

    assert iterations["n"] >= 2
