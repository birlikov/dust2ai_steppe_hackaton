from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

import pytest
from src.agents.claude_bridge import ClaudeBridge, ClaudeBridgeError
from src.core.config import get_settings
from src.storage import db
from src.storage import drafts as drafts_mod
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


@pytest.mark.parametrize(
    "reply",
    [
        "Let me check with the team and we'll get back to you within the hour.",
        "I'll ask Saule and circle back shortly.",
        "Let me check with Saule on the custom decoration.",
        "We'll respond as soon as we hear back.",
        "Getting back to you within 24 hours.",
    ],
)
@pytest.mark.asyncio
async def test_escalation_phrase_creates_inbox_draft(reply: str) -> None:
    """A persona promise to follow up should park a draft in /inbox."""
    bridge = _bridge_with(reply=reply)
    orch = Orchestrator(bridge=bridge)
    await orch.run(
        TurnRequest(
            channel="whatsapp",
            external_id="+15555550199",
            user_message="any chance of a peanut-free cake for tomorrow?",
        )
    )
    pending = await drafts_mod.list_status("pending")
    assert any(d.kind == "escalation_callback" for d in pending), (
        "expected an escalation_callback draft after escalation reply"
    )


@pytest.mark.parametrize(
    "reply",
    [
        'Yes — cake "Honey" is on the counter, 1.2 kg, $42.',
        "We have honey-cake slices today at $8.50.",
        "Pickup is available between 9 and 6 today.",
    ],
)
@pytest.mark.asyncio
async def test_normal_reply_does_not_create_escalation_draft(reply: str) -> None:
    """Concrete answers shouldn't queue an escalation."""
    bridge = _bridge_with(reply=reply)
    orch = Orchestrator(bridge=bridge)
    await orch.run(
        TurnRequest(
            channel="website",
            external_id="visitor-no-escalation",
            user_message="do you have honey cake?",
        )
    )
    pending = await drafts_mod.list_status("pending")
    assert not any(d.kind == "escalation_callback" for d in pending)


def _runner_with_stdout(stdout: bytes):
    async def runner(*_args: Iterable, **_kwargs: object) -> tuple[int, bytes, bytes]:
        return 0, stdout, b""

    return runner
