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
import os
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field

from src.agents.system_prompt import load_system_prompt
from src.core.config import get_settings
from src.core.logging import get_logger

log = get_logger(__name__)

# Public signature for an injected subprocess runner. Returns (returncode, stdout, stderr).
Runner = Callable[
    [list[str], bytes, Mapping[str, str], float],
    Awaitable[tuple[int, bytes, bytes]],
]


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
        argv = [self.command, "-p", "--system-prompt", self.system_prompt]

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
    """Build a bridge from settings + the composed persona. Side-effect free."""
    settings = get_settings()
    return ClaudeBridge(
        model=settings.anthropic_model,
        system_prompt=load_system_prompt(),
    )
