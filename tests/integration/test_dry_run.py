"""End-to-end dry-run integration test.

Spawns the stub MCP server as a subprocess, connects through our registry,
runs the agent loop with a respx-mocked Anthropic client, and verifies the
full pipe — config → MCP server → tool call → agent reply — works.

Marked with @pytest.mark.integration; skip in unit-only runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
import respx
from anthropic import AsyncAnthropic
from src.agents.loop import AgentLoop
from src.agents.models import Tier
from src.mcp.loader import McpConfig, StdioServer
from src.mcp.registry import McpRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
STUB_SERVER = REPO_ROOT / "examples" / "mcp_stub_server.py"


def _stub_config() -> McpConfig:
    return McpConfig(
        servers={
            "stub": StdioServer(
                transport="stdio",
                command=sys.executable,
                args=[str(STUB_SERVER)],
                env={},
            )
        }
    )


def _msg_response(stop_reason: str, content: list[dict]) -> dict:
    return {
        "id": "msg_x",
        "type": "message",
        "role": "assistant",
        "model": "claude-haiku-4-5",
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 5, "output_tokens": 5},
        "content": content,
    }


@pytest.mark.integration
async def test_registry_connects_and_lists_stub_tools() -> None:
    async with McpRegistry(config=_stub_config()) as reg:
        names = {t.tool_name for t in reg.tools}
        assert "lookup_business_info" in names
        assert "list_services" in names


@pytest.mark.integration
async def test_registry_calls_stub_tool() -> None:
    async with McpRegistry(config=_stub_config()) as reg:
        result = await reg.call(
            "stub__lookup_business_info", {"key": "hours"}
        )
        assert result["status"] == "ok"
        text_blocks = [c["text"] for c in result["data"] if c.get("type") == "text"]
        merged = json.loads(text_blocks[0]) if text_blocks else {}
        assert merged.get("status") == "ok"


@pytest.mark.integration
@respx.mock
async def test_agent_loop_through_stub_mcp() -> None:
    """The full pipe: agent decides to call lookup_business_info → stub returns
    hours → agent emits final answer."""
    route = respx.post("https://api.anthropic.com/v1/messages")
    route.side_effect = [
        httpx.Response(
            200,
            json=_msg_response(
                "tool_use",
                [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "stub__lookup_business_info",
                        "input": {"key": "hours"},
                    }
                ],
            ),
        ),
        httpx.Response(
            200,
            json=_msg_response(
                "end_turn",
                [{"type": "text", "text": "We're open Mon-Fri 9-6."}],
            ),
        ),
    ]

    async with McpRegistry(config=_stub_config()) as reg:
        loop = AgentLoop(
            registry=reg,
            client=AsyncAnthropic(api_key="test"),
            tier=Tier.CHEAP,
        )
        reply = await loop.run(
            system="Answer questions about the business.",
            user_message="when are you open?",
        )

    assert reply.iterations == 2
    assert reply.stopped_for == "end_turn"
    assert "Mon-Fri" in reply.text
    assert reply.tool_calls[0]["name"] == "stub__lookup_business_info"
