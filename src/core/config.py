"""Centralized config. All env vars and runtime knobs flow through here."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment + .env at repo root.

    Required vars are unset by default — production launch fails fast if
    they're missing. Optional vars have safe defaults for local dev.
    """

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Telegram ---
    telegram_bot_token: str = ""

    # --- Anthropic ---
    anthropic_api_key: str = ""
    anthropic_default_model: str = "claude-haiku-4-5"
    anthropic_max_tokens: int = 1024

    # --- Meta webhooks ---
    meta_verify_token: str = ""
    meta_app_secret: str = ""

    # --- MCP ---
    mcp_config_path: Path = Field(default=REPO_ROOT / "config" / "mcp.json")

    # --- Public URL (ngrok) ---
    public_url: str = ""
    ngrok_authtoken: str = ""
    ngrok_domain: str = ""

    # --- Storage ---
    sqlite_path: Path = Field(default=REPO_ROOT / "data" / "state.db")

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # human-readable in dev, JSON in prod


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
