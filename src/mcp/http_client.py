"""Thin async JSON-RPC client for the organizer-hosted ``happycake`` MCP server.

The server speaks **HTTPS + JSON-RPC 2.0**. Auth is a single ``X-Team-Token``
header. Every successful tool call returns:

    {"result": {"content": [{"type": "text", "text": "<JSON or CSV>"}]}}

Most tool payloads are JSON-stringified inside ``content[0].text`` —
:func:`call` parses that for you and returns the inner object. The single
exception is ``square_recent_sales_csv`` which returns raw CSV; pass
``raw_text=True`` for it.

This client is purpose-built for our server. The MCP Python SDK (``mcp``) does
not support HTTPS POST + JSON-RPC out of the box for our event server, so we
take the small dependency on ``httpx`` (already in the project) and call it
directly. Errors are surfaced as :class:`McpError`; callers can wrap with
:func:`src.core.retry.with_retry` for transient failures.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from src.core.config import get_settings
from src.core.logging import get_logger
from src.core.retry import RetryError, with_retry

log = get_logger(__name__)

DEFAULT_TIMEOUT_S = 5.0

# HTTP status thresholds. The server only ever returns success / 4xx-5xx;
# 4xx is permanent (auth, validation), 5xx is treated as transport-level.
_HTTP_BAD_REQUEST = 400
_HTTP_UNAUTHORIZED = 401
_HTTP_FORBIDDEN = 403
_HTTP_INTERNAL = 500


class McpError(RuntimeError):
    """Tool-level failure (server returned ``isError: true`` or JSON-RPC error)."""

    def __init__(self, message: str, *, code: int | None = None, raw: Any = None):
        super().__init__(message)
        self.code = code
        self.raw = raw


class McpTransportError(RuntimeError):
    """Network or HTTP failure that is potentially retryable."""


@dataclass(slots=True)
class HappycakeMcpClient:
    """Single-server JSON-RPC client. Pass an ``httpx.AsyncClient`` to share pooling."""

    url: str
    team_token: str
    timeout_s: float = DEFAULT_TIMEOUT_S
    _next_id: int = 0
    _http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> HappycakeMcpClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self.timeout_s)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    def _bump(self) -> int:
        self._next_id += 1
        return self._next_id

    async def call(
        self,
        tool: str,
        arguments: Mapping[str, Any] | None = None,
        *,
        raw_text: bool = False,
    ) -> Any:
        """Invoke a single MCP tool. Returns the parsed inner object (or raw CSV)."""
        if self._http is None:
            raise RuntimeError(
                "HappycakeMcpClient must be used as an async context manager"
            )
        body = {
            "jsonrpc": "2.0",
            "id": self._bump(),
            "method": "tools/call",
            "params": {"name": tool, "arguments": dict(arguments or {})},
        }
        try:
            resp = await self._http.post(
                self.url,
                headers={"X-Team-Token": self.team_token, "Content-Type": "application/json"},
                json=body,
            )
        except httpx.RequestError as exc:
            raise McpTransportError(str(exc)) from exc

        if resp.status_code >= _HTTP_INTERNAL:
            raise McpTransportError(f"server {resp.status_code}: {resp.text[:200]}")
        if resp.status_code in (_HTTP_UNAUTHORIZED, _HTTP_FORBIDDEN):
            raise McpError(f"auth failed ({resp.status_code})", code=resp.status_code)
        if resp.status_code >= _HTTP_BAD_REQUEST:
            raise McpError(
                f"client error {resp.status_code}: {resp.text[:200]}",
                code=resp.status_code,
            )

        try:
            envelope = resp.json()
        except json.JSONDecodeError as exc:
            raise McpError(f"non-JSON response: {resp.text[:200]}") from exc

        if "error" in envelope:
            err = envelope["error"]
            raise McpError(
                err.get("message", "rpc error"),
                code=err.get("code"),
                raw=err,
            )

        result = envelope.get("result", {})
        if result.get("isError"):
            text = _extract_text(result)
            raise McpError(text or "tool reported error", raw=result)

        text = _extract_text(result)
        if raw_text:
            return text
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Fallback: some tools may return non-JSON text — return as-is.
            return text


def _extract_text(result: Mapping[str, Any]) -> str:
    parts = result.get("content") or []
    for part in parts:
        if isinstance(part, Mapping) and part.get("type") == "text":
            text = part.get("text")
            if isinstance(text, str):
                return text
    return ""


def build_default_client() -> HappycakeMcpClient:
    """Build a client from settings. Side-effect free."""
    settings = get_settings()
    if not settings.sbc_team_token:
        raise RuntimeError(
            "SBC_TEAM_TOKEN is not set — copy config/.env.example to .env and fill it."
        )
    return HappycakeMcpClient(
        url=settings.sbc_mcp_url,
        team_token=settings.sbc_team_token,
    )


async def call_with_retry(
    client: HappycakeMcpClient,
    tool: str,
    arguments: Mapping[str, Any] | None = None,
    *,
    raw_text: bool = False,
    attempts: int = 3,
) -> Any:
    """Call a tool with the project's standard retry policy."""

    async def _once() -> Any:
        return await client.call(tool, arguments, raw_text=raw_text)

    try:
        return await with_retry(
            _once,
            attempts=attempts,
            retry_on=(McpTransportError,),
            label=f"mcp.call:{tool}",
        )
    except RetryError as exc:
        log.error("mcp.call_failed_after_retries", tool=tool, err=str(exc))
        raise McpTransportError(str(exc.__cause__ or exc)) from exc
