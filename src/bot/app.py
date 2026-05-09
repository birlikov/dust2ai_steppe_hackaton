"""Telegram bot app factory + polling entry point."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault

from src.agents.claude_bridge import ClaudeBridge, build_default_bridge
from src.bot.handlers import router
from src.bot.middleware import AuditMiddleware
from src.bot.storage import SqliteFsmStorage
from src.core.config import get_settings
from src.core.logging import get_logger
from src.storage import db

log = get_logger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Begin a session"),
    BotCommand(command="help", description="Show available commands"),
    BotCommand(command="cancel", description="Cancel the current operation"),
    BotCommand(command="restart", description="Wipe state and start over"),
]


async def sync_commands(bot: Bot) -> None:
    """Push the canonical command list to Telegram so the Menu button shows it."""
    await bot.set_my_commands(BOT_COMMANDS, scope=BotCommandScopeDefault())
    log.info("telegram.commands_synced", count=len(BOT_COMMANDS))


def build_bot() -> Bot:
    token = get_settings().telegram_bot_token
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not set — copy config/.env.example to .env"
        )
    return Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


def build_dispatcher() -> Dispatcher:
    dp = Dispatcher(storage=SqliteFsmStorage())
    dp.message.middleware(AuditMiddleware())
    dp.include_router(router)
    return dp


async def run_polling(bridge: ClaudeBridge | None = None) -> None:
    bot = build_bot()
    dp = build_dispatcher()
    await sync_commands(bot)
    log.info("telegram.start_polling")
    bridge = bridge or build_default_bridge()
    log.info("agent.ready", model=bridge.model, command=bridge.command)
    try:
        await dp.start_polling(
            bot,
            bridge=bridge,
            allowed_updates=dp.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()
        await db.close()


def main() -> None:
    """Synchronous entry: `uv run python -m src.bot.app`."""
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
