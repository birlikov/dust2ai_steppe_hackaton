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

    # --- Runtime LLM (claude -p subprocess) ---
    # Model is pinned via the ANTHROPIC_MODEL env var the bridge sets per call.
    # The brief mandates Opus 4.7; we expose it as a setting so tests can override.
    anthropic_model: str = "claude-opus-4-7"

    # --- Steppe Business Club hackathon MCP ---
    sbc_mcp_url: str = "https://www.steppebusinessclub.com/api/mcp"
    sbc_team_token: str = ""

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

    # --- Owner bot notifier ---
    notifier_interval_s: int = 1800  # 30 min between proactive checks
    owner_chat_id: int | None = None  # fallback if owner_identity isn't captured

    # --- Always-on world poller (sandbox listener) ---
    # Drains ``world_next_event`` continuously inside the bot process so
    # simulator-emitted WhatsApp / Instagram messages are routed through
    # the customer-facing orchestrator without needing a manual scenario
    # run. Disable when running ``scripts/run_scenario.py`` against the
    # same team token to avoid two consumers racing on the same timeline.
    world_poller_enabled: bool = True

    # --- Kitchen-staff side auto-loop (demo) ---
    # Closes the order → ticket → accept → ready loop in real time so
    # judges see the full POS+kitchen flow without needing a kitchen UI.
    # Off by default — flip to ``true`` for the demo. Polls
    # ``kitchen_list_tickets`` every ``kitchen_tick_s`` seconds;
    # capacity-aware (rejects when remaining < ``kitchen_reject_threshold_min``).
    kitchen_auto_demo: bool = True
    kitchen_tick_s: float = 20.0
    kitchen_reject_threshold_min: int = 30

    # If set, the bot only responds to chats paired by sending this exact
    # passphrase (or to the chat already in `owner_identity`). Unset → open
    # mode (dev / fresh-clone). Never commit a real value.
    owner_passphrase: str = ""

    # --- Logging ---
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_json: bool = False  # human-readable in dev, JSON in prod


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
