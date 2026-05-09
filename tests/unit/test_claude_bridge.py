from __future__ import annotations

from collections.abc import Mapping

import pytest
from src.agents.claude_bridge import (
    HISTORY_TURN_CAP,
    ClaudeBridge,
    ClaudeBridgeError,
    _build_prompt_body,
)


def _ok_runner(stdout: bytes, *, rc: int = 0, stderr: bytes = b""):
    captured: dict[str, object] = {}

    async def runner(
        argv: list[str],
        stdin: bytes,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> tuple[int, bytes, bytes]:
        captured["argv"] = argv
        captured["stdin"] = stdin
        captured["env"] = dict(env)
        captured["timeout_s"] = timeout_s
        return rc, stdout, stderr

    return runner, captured


def _bridge(runner) -> ClaudeBridge:
    return ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/usr/bin/true",
        runner=runner,
    )


@pytest.mark.asyncio
async def test_query_returns_stripped_stdout() -> None:
    runner, _ = _ok_runner(b"  hello, friend  \n")
    bridge = _bridge(runner)
    out = await bridge.query("hi")
    assert out == "hello, friend"


@pytest.mark.asyncio
async def test_query_passes_system_prompt_and_pinned_model() -> None:
    runner, captured = _ok_runner(b"ack")
    bridge = _bridge(runner)
    await bridge.query("hi")
    argv = captured["argv"]
    assert isinstance(argv, list)
    assert argv[0] == "/usr/bin/true"
    assert argv[1] == "-p"
    assert argv[2] == "--system-prompt"
    assert argv[3] == "SYS"
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["ANTHROPIC_MODEL"] == "claude-opus-4-7"


@pytest.mark.asyncio
async def test_query_pipes_prompt_body_via_stdin() -> None:
    runner, captured = _ok_runner(b"ok")
    bridge = _bridge(runner)
    await bridge.query("how late are you open?")
    stdin_blob = captured["stdin"]
    assert isinstance(stdin_blob, bytes)
    assert b"how late are you open?" in stdin_blob


@pytest.mark.asyncio
async def test_query_includes_history_block_when_history_given() -> None:
    runner, captured = _ok_runner(b"ok")
    bridge = _bridge(runner)
    history = [
        {"role": "user", "content": "do you have honey cake?"},
        {"role": "assistant", "content": "yes — 1.2 kg, $42"},
    ]
    await bridge.query("can I get one for tomorrow?", history=history)
    blob = captured["stdin"]
    assert isinstance(blob, bytes)
    text = blob.decode("utf-8")
    assert "Recent conversation" in text
    assert "User: do you have honey cake?" in text
    assert "Assistant: yes — 1.2 kg, $42" in text
    assert "Current message" in text
    assert "can I get one for tomorrow?" in text


@pytest.mark.asyncio
async def test_query_raises_on_nonzero_exit() -> None:
    runner, _ = _ok_runner(b"", rc=1, stderr=b"boom")
    bridge = _bridge(runner)
    with pytest.raises(ClaudeBridgeError, match="exited 1"):
        await bridge.query("hi")


@pytest.mark.asyncio
async def test_query_wraps_missing_cli_error() -> None:
    async def missing_runner(*_args, **_kwargs):
        raise FileNotFoundError("claude")

    bridge = ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/no/such/claude",
        runner=missing_runner,
    )
    with pytest.raises(ClaudeBridgeError, match="claude CLI not found"):
        await bridge.query("hi")


@pytest.mark.asyncio
async def test_query_wraps_timeout() -> None:
    async def timeout_runner(*_args, **_kwargs):
        raise TimeoutError

    bridge = ClaudeBridge(
        model="claude-opus-4-7",
        system_prompt="SYS",
        command="/usr/bin/true",
        runner=timeout_runner,
        timeout_s=5.0,
    )
    with pytest.raises(ClaudeBridgeError, match="timed out"):
        await bridge.query("hi")


def test_build_prompt_body_returns_message_when_history_empty() -> None:
    assert _build_prompt_body("  hello  ", None) == "hello"
    assert _build_prompt_body("hello", []) == "hello"


def test_build_prompt_body_caps_history_to_n_turns() -> None:
    long_history = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"t{i}"}
        for i in range(HISTORY_TURN_CAP * 3)
    ]
    body = _build_prompt_body("now", long_history)
    # First two turns must have rolled out of the window.
    assert "t0" not in body
    assert "t1" not in body
    # Last turn must be present.
    last_idx = HISTORY_TURN_CAP * 3 - 1
    assert f"t{last_idx}" in body


def test_build_prompt_body_skips_malformed_turns() -> None:
    history = [
        {"role": "system", "content": "should drop"},
        {"role": "user", "content": ""},
        {"role": "user", "content": "kept"},
    ]
    body = _build_prompt_body("now", history)
    assert "should drop" not in body
    assert "User: kept" in body
