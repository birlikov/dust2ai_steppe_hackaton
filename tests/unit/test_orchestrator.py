from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.config import get_settings
from src.storage import db
from src.workflows.orchestrator import (
    Orchestrator,
    OrchestratorError,
    TurnRequest,
)


@pytest.fixture(autouse=True)
async def _isolate_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "sqlite_path", tmp_path / "orchestrator_test.db")
    await db.close()
    yield
    await db.close()


def _bridge_with(reply: str | None = None, raise_exc: Exception | None = None) -> ClaudeBridge:
    async def runner(
        argv: list[str],
        stdin: bytes,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, bytes, bytes]:
        if raise_exc is not None:
            raise raise_exc
        return 0, (reply or "").encode("utf-8"), b""

    return ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/usr/bin/true",
        runner=runner,
    )


@pytest.mark.asyncio
async def test_run_returns_bridge_reply_and_persists_history() -> None:
    bridge = _bridge_with(reply='Cake "Honey" is on the counter — 1.2 kg, $42.')
    orch = Orchestrator(bridge=bridge)

    out = await orch.run(
        TurnRequest(
            channel="website",
            external_id="visitor-1",
            user_message="hi do you have honey?",
        )
    )

    assert out.session_id
    assert "1.2 kg" in out.reply
    assert out.voice_warnings == []

    out2 = await orch.run(
        TurnRequest(
            channel="website",
            external_id="visitor-1",
            user_message="and the napoleon?",
        )
    )
    assert out2.session_id == out.session_id


@pytest.mark.asyncio
async def test_voice_warnings_surface_violations_without_blocking() -> None:
    bridge = _bridge_with(reply="Welcome to Happy Cake Sugar Land — amazing flavours!")
    orch = Orchestrator(bridge=bridge)

    out = await orch.run(
        TurnRequest(
            channel="whatsapp",
            external_id="+12815550100",
            user_message="hi",
        )
    )

    rule_ids = [v.rule_id for v in out.voice_warnings]
    assert "brand.r2" in rule_ids  # Happy Cake split
    assert "brand.r10" in rule_ids  # amazing
    # Reply still flows through; the orchestrator does not block on warnings.
    assert "Happy Cake" in out.reply


@pytest.mark.asyncio
async def test_bridge_failure_raises_orchestrator_error() -> None:
    bridge = _bridge_with(raise_exc=ClaudeBridgeError("boom"))
    orch = Orchestrator(bridge=bridge)

    with pytest.raises(OrchestratorError):
        await orch.run(
            TurnRequest(
                channel="website",
                external_id="visitor-2",
                user_message="hi",
            )
        )


@pytest.mark.asyncio
async def test_empty_reply_normalised_to_placeholder() -> None:
    bridge = _bridge_with(reply="")
    orch = Orchestrator(bridge=bridge)
    out = await orch.run(
        TurnRequest(
            channel="website",
            external_id="visitor-3",
            user_message="hi",
        )
    )
    assert out.reply == "(no response)"


def _runner_with_stdout(stdout: bytes):
    async def runner(*_args: Iterable, **_kwargs: object) -> tuple[int, bytes, bytes]:
        return 0, stdout, b""

    return runner
