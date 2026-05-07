"""Convert MCP tools to Anthropic tool-use format.

Anthropic's `tools` parameter expects:
    [{"name": "...", "description": "...", "input_schema": {...}}]

Tool names must match `^[a-zA-Z0-9_-]{1,64}$`. Our namespaced format
`<server>__<tool>` already satisfies that.
"""

from __future__ import annotations

from typing import Any

from src.mcp.registry import RegisteredTool


def to_anthropic_tools(tools: list[RegisteredTool]) -> list[dict[str, Any]]:
    return [
        {
            "name": t.namespaced_name,
            "description": t.description,
            "input_schema": t.input_schema or {"type": "object", "properties": {}},
        }
        for t in tools
    ]
