"""Telegram bot app factory + polling entry point."""

from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeDefault

from src.agents.claude_bridge import ClaudeBridge, build_default_bridge
from src.bot.handlers import router as commands_router
from src.bot.middleware import AuditMiddleware
from src.bot.owner_commands import router as owner_router
from src.bot.storage import SqliteFsmStorage
from src.core.config import get_settings
from src.core.logging import get_logger
from src.mcp.http_client import HappycakeMcpClient, build_default_client
from src.storage import db

log = get_logger(__name__)

BOT_COMMANDS: list[BotCommand] = [
    BotCommand(command="start", description="Begin a session"),
    BotCommand(command="help", description="Show available commands"),
    BotCommand(command="dashboard", description="Sales / kitchen / evaluator snapshot"),
    BotCommand(command="budget", description="Marketing budget + recent leads"),
    BotCommand(command="drafts", description="Review pending drafts"),
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
    # Owner commands first so /dashboard etc. don't fall through to free-text.
    dp.include_router(owner_router)
    dp.include_router(commands_router)
    return dp


async def run_polling(
    bridge: ClaudeBridge | None = None,
    mcp: HappycakeMcpClient | None = None,
) -> None:
    bot = build_bot()
    dp = build_dispatcher()
    await sync_commands(bot)
    log.info("telegram.start_polling")
    bridge = bridge or build_default_bridge()
    log.info("agent.ready", model=bridge.model, command=bridge.command)

    owns_mcp = False
    if mcp is None:
        try:
            mcp = await build_default_client().__aenter__()
            owns_mcp = True
        except Exception as exc:  # pragma: no cover - boot diagnostic
            log.warning("mcp.boot_skipped", err=str(exc))
            mcp = None

    try:
        if mcp is not None:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                bridge=bridge,
                mcp=mcp,
            )
        else:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                bridge=bridge,
            )
    finally:
        if owns_mcp and mcp is not None:
            await mcp.__aexit__(None, None, None)
        await bot.session.close()
        await db.close()


def main() -> None:
    """Synchronous entry: `uv run python -m src.bot.app`."""
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
