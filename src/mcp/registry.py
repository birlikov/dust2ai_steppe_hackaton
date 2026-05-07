"""MCP server registry — owns per-server sessions and namespaced tool dispatch.

Tools are exposed under `<server>__<tool>` so multiple servers can define
overlapping names without collision.
"""

from __future__ import annotations

import contextlib
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Any

from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from mcp import ClientSession
from src.core.errors import ToolResult, error, ok
from src.core.logging import get_logger
from src.mcp.loader import McpConfig, ServerConfig, SseServer, StdioServer

log = get_logger(__name__)

NAMESPACE_SEP = "__"


@dataclass(slots=True)
class RegisteredTool:
    namespaced_name: str  # e.g. "sandbox__lookup_customer"
    server: str
    tool_name: str
    description: str
    input_schema: dict[str, Any]


@dataclass
class McpRegistry:
    config: McpConfig
    _sessions: dict[str, ClientSession] = field(default_factory=dict)
    _stack: AsyncExitStack = field(default_factory=AsyncExitStack)
    _tools: dict[str, RegisteredTool] = field(default_factory=dict)

    async def __aenter__(self) -> McpRegistry:
        for name, cfg in self.config.servers.items():
            try:
                session = await self._connect(name, cfg)
                self._sessions[name] = session
                await self._index_tools(name, session)
            except Exception as exc:
                log.error("mcp.connect_failed", server=name, err=str(exc))
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._stack.aclose()
        self._sessions.clear()
        self._tools.clear()

    async def _connect(self, name: str, cfg: ServerConfig) -> ClientSession:
        if isinstance(cfg, StdioServer):
            params = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env)
            read, write = await self._stack.enter_async_context(stdio_client(params))
        elif isinstance(cfg, SseServer):
            read, write = await self._stack.enter_async_context(
                sse_client(cfg.url, headers=cfg.headers or None)
            )
        else:  # pragma: no cover - exhaustiveness
            raise TypeError(f"unknown transport: {cfg!r}")

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        log.info("mcp.connected", server=name)
        return session

    async def _index_tools(self, server: str, session: ClientSession) -> None:
        result = await session.list_tools()
        for t in result.tools:
            namespaced = f"{server}{NAMESPACE_SEP}{t.name}"
            self._tools[namespaced] = RegisteredTool(
                namespaced_name=namespaced,
                server=server,
                tool_name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema,
            )
        log.info("mcp.indexed", server=server, count=len(result.tools))

    @property
    def tools(self) -> list[RegisteredTool]:
        return list(self._tools.values())

    def get(self, namespaced_name: str) -> RegisteredTool | None:
        return self._tools.get(namespaced_name)

    async def call(self, namespaced_name: str, arguments: dict[str, Any]) -> ToolResult:
        """Dispatch a tool call to the owning server. Returns a ToolResult envelope."""
        tool = self._tools.get(namespaced_name)
        if tool is None:
            return error(f"unknown tool: {namespaced_name}")
        session = self._sessions.get(tool.server)
        if session is None:
            return error(f"server unavailable: {tool.server}")
        try:
            result = await session.call_tool(tool.tool_name, arguments=arguments)
        except Exception as exc:
            log.exception("mcp.call_failed", tool=namespaced_name)
            return error(str(exc))

        if getattr(result, "isError", False):
            text = _extract_text(result.content)
            return error(text or "tool reported error")

        return ok(_serialize_content(result.content))


def _extract_text(content: Any) -> str:
    parts: list[str] = []
    for c in content or []:
        text = getattr(c, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _serialize_content(content: Any) -> Any:
    """MCP content is a list of typed parts. Most tools return a single text part
    that is itself JSON. We return the raw list of {type, text|...} dicts and let
    callers parse if needed.
    """
    out: list[dict[str, Any]] = []
    for c in content or []:
        kind = getattr(c, "type", "unknown")
        item: dict[str, Any] = {"type": kind}
        text = getattr(c, "text", None)
        if text is not None:
            item["text"] = text
        data = getattr(c, "data", None)
        if data is not None:
            item["data"] = data
        out.append(item)
    return out


@contextlib.asynccontextmanager
async def open_registry(config: McpConfig) -> Any:
    """Async context manager wrapping McpRegistry lifecycle."""
    reg = McpRegistry(config=config)
    async with reg:
        yield reg
