"""Agent loop tests using a stub registry and respx-mocked Anthropic API."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import respx
from anthropic import AsyncAnthropic
from src.agents.loop import AgentLoop
from src.agents.models import Tier
from src.core.errors import not_found, ok
from src.mcp.loader import McpConfig
from src.mcp.registry import McpRegistry, RegisteredTool


def _make_registry(tools: list[RegisteredTool], call_result: Any) -> McpRegistry:
    reg = McpRegistry(config=McpConfig())
    for t in tools:
        reg._tools[t.namespaced_name] = t
    reg.call = AsyncMock(return_value=call_result)  # type: ignore[method-assign]
    return reg


def _msg_response(stop_reason: str, content: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 10},
        "content": content,
    }


@respx.mock
async def test_loop_returns_text_on_end_turn() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_msg_response(
                "end_turn", [{"type": "text", "text": "Hello, Aida!"}]
            ),
        )
    )
    client = AsyncAnthropic(api_key="test")
    reg = _make_registry([], ok({}))
    loop = AgentLoop(registry=reg, client=client, tier=Tier.CHEAP)
    reply = await loop.run(system="You are helpful.", user_message="hi")
    assert reply.text == "Hello, Aida!"
    assert reply.iterations == 1
    assert reply.stopped_for == "end_turn"


@respx.mock
async def test_loop_dispatches_tool_then_finishes() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages")
    route.side_effect = [
        httpx.Response(
            200,
            json=_msg_response(
                "tool_use",
                [
                    {
                        "type": "tool_use",
                        "id": "tool_1",
                        "name": "sandbox__lookup_customer",
                        "input": {"phone": "+15551234567"},
                    }
                ],
            ),
        ),
        httpx.Response(
            200,
            json=_msg_response(
                "end_turn", [{"type": "text", "text": "Found you."}]
            ),
        ),
    ]
    tool = RegisteredTool(
        namespaced_name="sandbox__lookup_customer",
        server="sandbox",
        tool_name="lookup_customer",
        description="Find a customer by phone.",
        input_schema={"type": "object", "properties": {"phone": {"type": "string"}}},
    )
    reg = _make_registry([tool], not_found("missing"))
    loop = AgentLoop(
        registry=reg,
        client=AsyncAnthropic(api_key="test"),
        tier=Tier.CHEAP,
    )
    reply = await loop.run(system="...", user_message="who am i?")

    assert reply.iterations == 2
    assert reply.stopped_for == "end_turn"
    assert reply.text == "Found you."
    assert len(reply.tool_calls) == 1
    assert reply.tool_calls[0]["name"] == "sandbox__lookup_customer"
    reg.call.assert_awaited_once()  # type: ignore[attr-defined]


@respx.mock
async def test_loop_caps_at_max_iters() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json=_msg_response(
                "tool_use",
                [
                    {
                        "type": "tool_use",
                        "id": "t",
                        "name": "sandbox__noop",
                        "input": {},
                    }
                ],
            ),
        )
    )
    tool = RegisteredTool(
        namespaced_name="sandbox__noop",
        server="sandbox",
        tool_name="noop",
        description="",
        input_schema={"type": "object", "properties": {}},
    )
    reg = _make_registry([tool], ok({}))
    loop = AgentLoop(
        registry=reg,
        client=AsyncAnthropic(api_key="test"),
        tier=Tier.CHEAP,
        max_iters=3,
    )
    reply = await loop.run(system="s", user_message="u")
    assert reply.iterations == 3
    assert reply.stopped_for == "max_iters"
