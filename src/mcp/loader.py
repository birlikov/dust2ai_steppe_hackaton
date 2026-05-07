"""Load MCP server configurations from config/mcp.json."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from src.core.config import get_settings


class StdioServer(BaseModel):
    transport: Literal["stdio"]
    command: str
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)


class SseServer(BaseModel):
    transport: Literal["sse"]
    url: str
    headers: dict[str, str] = Field(default_factory=dict)


ServerConfig = StdioServer | SseServer


class McpConfig(BaseModel):
    servers: dict[str, ServerConfig] = Field(default_factory=dict)


def load_config(path: Path | None = None) -> McpConfig:
    """Load and validate config/mcp.json.

    Returns an empty config if the file is the placeholder (no `servers` key
    or empty dict). Raises ValueError on malformed JSON.
    """
    cfg_path = path or get_settings().mcp_config_path
    if not cfg_path.exists():
        return McpConfig()

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    # Strip placeholder-only comment fields
    raw = {k: v for k, v in raw.items() if not k.startswith("_")}
    return McpConfig.model_validate(raw)
