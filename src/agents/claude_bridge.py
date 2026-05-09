"""Async subprocess bridge to ``claude -p`` (Claude Code headless).

The runtime LLM is **not** the Anthropic SDK — the brief allows ``claude -p`` and
disallows other LLM providers for the core runtime. This module is the thin shim that
the bot uses to ask the runtime persona a question. It:

  - Composes the system prompt by reading ``agent/*.md`` (via ``system_prompt.py``).
  - Pre-pends a short, formatted history block to the user message so the runtime sees
    conversation context without needing a server-side session.
  - Pins the model to ``claude-opus-4-7`` via the ``ANTHROPIC_MODEL`` env var (the
    brief mandates Opus 4.7).
  - Hands subprocess execution to a small ``runner`` callable that tests can swap.

The bridge does not know about MCP tools — those reach the runtime through Claude
Code's own MCP plumbing (``.claude/settings.local.json``). The bridge's job is one
exchange of text in, one exchange of text out.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
)
from dataclasses import dataclass, field
from typing import Any

from src.agents.system_prompt import load_owner_system_prompt, load_system_prompt
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger(__name__)

# Public signature for an injected subprocess runner. Returns (returncode, stdout, stderr).
Runner = Callable[
    [list[str], bytes, Mapping[str, str], float],
    Awaitable[tuple[int, bytes, bytes]],
]

# Streaming runner — yields each stdout line as bytes (incl. trailing newline).
# Wrapped in a no-arg callable so the dataclass can default-store the function.
StreamingRunner = Callable[
    [list[str], bytes, Mapping[str, str], float],
    AsyncIterator[bytes],
]

# Callback type for streaming events: receives one parsed JSONL event at a time.
EventCallback = Callable[[dict[str, Any]], Awaitable[None]]


class ClaudeBridgeError(RuntimeError):
    """Raised when the ``claude -p`` subprocess fails or times out."""


HISTORY_TURN_CAP = 12  # last N user/assistant turns prepended to each prompt
PROMPT_HEADER = "## Recent conversation\n"
PROMPT_FOOTER = "\n## Current message\n"


async def _default_runner(
    argv: list[str],
    stdin: bytes,
    env: Mapping[str, str],
    timeout_s: float,
) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin), timeout=timeout_s
        )
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, stdout, stderr


async def _default_streaming_runner(
    argv: list[str],
    stdin: bytes,
    env: Mapping[str, str],
    timeout_s: float,
) -> AsyncIterator[bytes]:
    """Run ``claude -p --output-format stream-json`` and yield each stdout line.

    Each yield is one JSONL line (terminated by ``\\n``). Lines that look
    like partial JSON are buffered until a complete line lands.
    """
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(env),
    )
    if proc.stdin is not None:
        proc.stdin.write(stdin)
        await proc.stdin.drain()
        proc.stdin.close()

    deadline = asyncio.get_event_loop().time() + timeout_s
    try:
        assert proc.stdout is not None
        while True:
            remaining = max(0.5, deadline - asyncio.get_event_loop().time())
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=remaining)
            if not line:
                break
            yield line
    except TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    finally:
        # Ensure the process is reaped even if the consumer breaks early.
        if proc.returncode is None:
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()


@dataclass(slots=True)
class ClaudeBridge:
    """Thin wrapper around ``claude -p`` for one-shot non-interactive prompts.

    Construct with :func:`build_default_bridge` for the production path, or pass a
    custom ``runner`` in tests to avoid spawning the real CLI.
    """

    model: str
    system_prompt: str
    command: str = "claude"
    timeout_s: float = 120.0
    runner: Runner = field(default=_default_runner, repr=False)
    streaming_runner: StreamingRunner = field(
        default=_default_streaming_runner, repr=False
    )

    async def query(
        self,
        user_message: str,
        history: Iterable[Mapping[str, str]] | None = None,
    ) -> str:
        """Run one prompt through ``claude -p`` and return the model's text reply.

        ``history`` is an iterable of ``{"role": "user" | "assistant", "content": str}``
        dicts ordered oldest-first. Only the last :data:`HISTORY_TURN_CAP` turns are
        kept. The full prompt body is built locally and passed via stdin.
        """
        body = _build_prompt_body(user_message, history)
        env = {**os.environ, "ANTHROPIC_MODEL": self.model}
        argv = [
            self.command,
            "-p",
            # bypassPermissions lets the headless subprocess call MCP tools
            # without an interactive permission prompt. The persona's hard
            # rules constrain *which* tools — see owner_agent/RULES.md and
            # agent/RULES.md. settings.local.json's permissions.allow list
            # is the secondary belt-and-suspenders guard.
            "--permission-mode",
            "bypassPermissions",
            "--system-prompt",
            self.system_prompt,
        ]

        try:
            rc, stdout, stderr = await self.runner(
                argv, body.encode("utf-8"), env, self.timeout_s
            )
        except TimeoutError as exc:
            log.error("claude_bridge.timeout", timeout=self.timeout_s)
            raise ClaudeBridgeError(
                f"claude -p timed out after {self.timeout_s:.0f}s"
            ) from exc
        except FileNotFoundError as exc:
            raise ClaudeBridgeError(
                f"claude CLI not found on PATH (looked for {self.command!r}). "
                "Install Claude Code or set the bridge `command`."
            ) from exc

        if rc != 0:
            err_excerpt = stderr.decode("utf-8", errors="replace")[:500]
            log.error("claude_bridge.nonzero_exit", rc=rc, stderr=err_excerpt)
            raise ClaudeBridgeError(
                f"claude -p exited {rc}: {err_excerpt or '(no stderr)'}"
            )

        return stdout.decode("utf-8", errors="replace").strip()

    async def query_streaming(
        self,
        user_message: str,
        on_event: EventCallback,
        history: Iterable[Mapping[str, str]] | None = None,
    ) -> str:
        """Stream agent events while running one prompt through ``claude -p``.

        The runtime emits JSONL events (``message_start``, ``content_block_start``
        for tool calls, ``text_delta``, ``user`` events containing
        ``tool_use_result``, and a final ``result`` event with the cleaned
        assistant text). Each parsed event is forwarded to ``on_event``; the
        bridge accumulates and returns the final assistant text.

        Defensive parsing — malformed lines are logged and skipped, never raised.
        """
        body = _build_prompt_body(user_message, history)
        env = {**os.environ, "ANTHROPIC_MODEL": self.model}
        argv = [
            self.command,
            "-p",
            "--permission-mode",
            "bypassPermissions",
            "--output-format",
            "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--system-prompt",
            self.system_prompt,
        ]

        final_text_parts: list[str] = []
        try:
            async for raw_line in self.streaming_runner(
                argv, body.encode("utf-8"), env, self.timeout_s
            ):
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    log.debug("claude_bridge.bad_json_line", err=str(exc))
                    continue
                if not isinstance(event, dict):
                    continue
                try:
                    await on_event(event)
                except Exception:
                    log.exception("claude_bridge.on_event_failed")
                _accumulate_final_text(event, final_text_parts)
        except TimeoutError as exc:
            log.error("claude_bridge.stream_timeout", timeout=self.timeout_s)
            raise ClaudeBridgeError(
                f"claude -p timed out after {self.timeout_s:.0f}s"
            ) from exc
        except FileNotFoundError as exc:
            raise ClaudeBridgeError(
                f"claude CLI not found on PATH (looked for {self.command!r})."
            ) from exc

        return "".join(final_text_parts).strip()


def _accumulate_final_text(
    event: dict[str, Any], parts: list[str]
) -> None:
    """Pick out final-assistant text from streaming events."""
    event_type = event.get("type")
    if event_type == "result":
        text = event.get("result")
        if isinstance(text, str) and text:
            parts.clear()
            parts.append(text)
        return
    if event_type == "assistant":
        message = event.get("message")
        if isinstance(message, dict):
            for block in message.get("content", []) or []:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and isinstance(block.get("text"), str)
                ):
                    parts.append(block["text"])


def _build_prompt_body(
    user_message: str,
    history: Iterable[Mapping[str, str]] | None,
) -> str:
    turns = list(history or [])
    if not turns:
        return user_message.strip()

    capped = turns[-HISTORY_TURN_CAP:]
    formatted_lines: list[str] = []
    for turn in capped:
        role = str(turn.get("role", "")).strip().lower()
        content = str(turn.get("content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        prefix = "User" if role == "user" else "Assistant"
        formatted_lines.append(f"{prefix}: {content}")

    if not formatted_lines:
        return user_message.strip()

    return (
        PROMPT_HEADER
        + "\n".join(formatted_lines)
        + PROMPT_FOOTER
        + user_message.strip()
    )


def build_default_bridge() -> ClaudeBridge:
    """Build the customer-facing bridge from settings + ``agent/``."""
    settings = get_settings()
    return ClaudeBridge(
        model=settings.anthropic_model,
        system_prompt=load_system_prompt(),
    )


def build_owner_bridge() -> ClaudeBridge:
    """Build the owner-facing operations-assistant bridge from ``owner_agent/``."""
    settings = get_settings()
    return ClaudeBridge(
        model=settings.anthropic_model,
        system_prompt=load_owner_system_prompt(),
    )
