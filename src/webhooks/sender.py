"""MessageSender abstraction.

Two implementations are pre-wired so we can flip strategy at H+0 once we know
how the organizer's bridge wants the reply delivered:

- ``McpToolSender``     — call a `send_<channel>_reply` tool on an MCP server
- ``WebhookResponseSender`` — return the reply in the HTTP response body
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.core.errors import ToolResult, error, ok
from src.mcp.registry import McpRegistry


class MessageSender(Protocol):
    async def send(
        self,
        channel: str,
        recipient: str,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> ToolResult: ...


@dataclass(slots=True)
class McpToolSender:
    """Routes outbound replies through an MCP tool named `send_{channel}_reply`."""

    registry: McpRegistry
    server: str  # MCP server hosting the send tool

    async def send(
        self,
        channel: str,
        recipient: str,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        tool_name = f"{self.server}__send_{channel}_reply"
        if self.registry.get(tool_name) is None:
            return error(f"send tool not found: {tool_name}")
        args: dict[str, Any] = {"recipient": recipient, "text": text}
        if idempotency_key is not None:
            args["idempotency_key"] = idempotency_key
        return await self.registry.call(tool_name, args)


@dataclass(slots=True)
class WebhookResponseSender:
    """Holds the reply for the route handler to embed in the HTTP response.

    Use when the organizer's bridge picks up replies from the response body.
    The handler reads `pop_pending(recipient)` after the agent loop finishes.
    """

    _pending: dict[str, str]

    def __init__(self) -> None:
        self._pending = {}

    async def send(
        self,
        channel: str,
        recipient: str,
        text: str,
        *,
        idempotency_key: str | None = None,
    ) -> ToolResult:
        del channel, idempotency_key  # unused — single-pending model
        self._pending[recipient] = text
        return ok({"queued": True})

    def pop_pending(self, recipient: str) -> str | None:
        return self._pending.pop(recipient, None)
