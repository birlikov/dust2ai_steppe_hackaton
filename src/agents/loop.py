"""Anthropic tool-use agent loop with prompt caching.

The loop:
  1. Send user message + system prompt + tool defs (cached) to Anthropic
  2. If stop_reason == "tool_use", dispatch each tool call, append results, repeat
  3. If stop_reason == "end_turn" (or max_iters hit), return the assistant text

Tools come from an MCP registry; results are wrapped as ToolResult envelopes
(see src/core/errors). The registry is the only place tools are defined —
local tools can be added later by extending the dispatch function.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from anthropic import AsyncAnthropic
from anthropic.types import Message, MessageParam

from src.agents.models import Tier, model_for
from src.core.config import get_settings
from src.core.logging import get_logger
from src.mcp.anthropic_tools import to_anthropic_tools
from src.mcp.registry import McpRegistry

log = get_logger(__name__)

DEFAULT_MAX_ITERS = 8


ToolDispatcher = Callable[[str, dict[str, Any]], Any]
"""Async callable: (tool_name, arguments) -> ToolResult-like dict."""


@dataclass(slots=True)
class AgentReply:
    text: str
    iterations: int
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    stopped_for: str = "end_turn"


@dataclass(slots=True)
class AgentLoop:
    registry: McpRegistry
    client: AsyncAnthropic | None = None
    tier: Tier = Tier.CHEAP
    max_iters: int = DEFAULT_MAX_ITERS
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        if self.client is None:
            self.client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)

    async def run(
        self,
        system: str,
        user_message: str,
        history: list[MessageParam] | None = None,
    ) -> AgentReply:
        """Run the loop until the model emits a final answer or we hit max_iters."""
        assert self.client is not None
        messages: list[MessageParam] = list(history or [])
        messages.append({"role": "user", "content": user_message})

        tools = to_anthropic_tools(self.registry.tools)
        cached_tools = _apply_cache(tools)

        observed_tool_calls: list[dict[str, Any]] = []
        last_text = ""

        for iteration in range(1, self.max_iters + 1):
            response: Message = await self.client.messages.create(
                model=model_for(self.tier),
                max_tokens=self.max_tokens,
                system=[
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
                tools=cached_tools,  # type: ignore[arg-type]
                messages=messages,
            )

            assistant_blocks = [_block_to_dict(b) for b in response.content]
            messages.append(
                {"role": "assistant", "content": assistant_blocks}  # type: ignore[typeddict-item]
            )

            last_text = _extract_text(response.content)

            if response.stop_reason != "tool_use":
                log.info(
                    "agent.done",
                    iters=iteration,
                    stop=response.stop_reason,
                    tool_calls=len(observed_tool_calls),
                )
                return AgentReply(
                    text=last_text,
                    iterations=iteration,
                    tool_calls=observed_tool_calls,
                    stopped_for=response.stop_reason or "end_turn",
                )

            tool_results: list[dict[str, Any]] = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                call_record = {"name": block.name, "input": dict(block.input)}
                observed_tool_calls.append(call_record)
                result = await self.registry.call(block.name, dict(block.input))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )
            messages.append(
                {"role": "user", "content": tool_results}  # type: ignore[typeddict-item]
            )

        log.warning("agent.max_iters_reached", iters=self.max_iters)
        return AgentReply(
            text=last_text or "(no response — max iterations reached)",
            iterations=self.max_iters,
            tool_calls=observed_tool_calls,
            stopped_for="max_iters",
        )


def _apply_cache(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark the last tool definition with cache_control: ephemeral.

    Anthropic caches everything up to the last cache_control marker. Setting
    it on the last tool means system + all tools get cached as one block.
    """
    if not tools:
        return tools
    out = [dict(t) for t in tools]
    out[-1] = {**out[-1], "cache_control": {"type": "ephemeral"}}
    return out


def _block_to_dict(block: Any) -> dict[str, Any]:
    """Convert anthropic content block to a plain dict for re-sending."""
    if hasattr(block, "model_dump"):
        result = block.model_dump()
        return result if isinstance(result, dict) else {"raw": result}
    return {"type": getattr(block, "type", "unknown")}


def _extract_text(content: list[Any]) -> str:
    parts: list[str] = []
    for b in content:
        if getattr(b, "type", None) == "text":
            parts.append(b.text)
    return "".join(parts).strip()
