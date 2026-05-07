"""Unit tests for MCP config loader."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from src.mcp.loader import McpConfig, SseServer, StdioServer, load_config


def test_empty_config_when_no_servers(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"servers": {}}))
    cfg = load_config(p)
    assert cfg.servers == {}


def test_strips_underscore_comment_keys(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"_comment": "ignore me", "servers": {}}))
    cfg = load_config(p)
    assert cfg == McpConfig(servers={})


def test_parses_stdio_server(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "servers": {
                    "local": {
                        "transport": "stdio",
                        "command": "python",
                        "args": ["server.py"],
                    }
                }
            }
        )
    )
    cfg = load_config(p)
    assert isinstance(cfg.servers["local"], StdioServer)
    assert cfg.servers["local"].command == "python"


def test_parses_sse_server(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(
        json.dumps(
            {
                "servers": {
                    "remote": {
                        "transport": "sse",
                        "url": "https://example.com/mcp",
                        "headers": {"Authorization": "Bearer x"},
                    }
                }
            }
        )
    )
    cfg = load_config(p)
    assert isinstance(cfg.servers["remote"], SseServer)
    assert cfg.servers["remote"].url == "https://example.com/mcp"


def test_returns_empty_when_path_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.json")
    assert cfg.servers == {}


def test_invalid_transport_raises(tmp_path: Path) -> None:
    p = tmp_path / "mcp.json"
    p.write_text(json.dumps({"servers": {"x": {"transport": "carrier-pigeon"}}}))
    with pytest.raises(ValueError):
        load_config(p)
