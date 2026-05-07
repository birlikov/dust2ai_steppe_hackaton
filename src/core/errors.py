"""Typed error envelopes. Tools never raise across module boundaries — they
return one of these shapes so the agent can handle them uniformly."""

from __future__ import annotations

from typing import Any, Literal, TypedDict

ToolStatus = Literal["ok", "not_found", "invalid_input", "rate_limited", "error"]


class ToolResult(TypedDict, total=False):
    """Canonical shape for any tool call result.

    `status` is always present. Extra keys depend on the tool.
    """

    status: ToolStatus
    reason: str  # human-readable when status != "ok"
    data: Any  # tool-specific payload when status == "ok"


def ok(data: Any = None, **extra: Any) -> ToolResult:
    return {"status": "ok", "data": data, **extra}  # type: ignore[typeddict-item]


def not_found(reason: str, **extra: Any) -> ToolResult:
    return {"status": "not_found", "reason": reason, **extra}  # type: ignore[typeddict-item]


def invalid_input(reason: str, **extra: Any) -> ToolResult:
    return {"status": "invalid_input", "reason": reason, **extra}  # type: ignore[typeddict-item]


def error(reason: str, **extra: Any) -> ToolResult:
    return {"status": "error", "reason": reason, **extra}  # type: ignore[typeddict-item]
