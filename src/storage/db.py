"""SQLite connection management + migration runner.

Uses aiosqlite. One connection per process is enough for our scale (single
host, no concurrent writers from outside this process). Connections are
created on first use and cached.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

from src.core.config import REPO_ROOT, get_settings
from src.core.logging import get_logger

log = get_logger(__name__)

MIGRATIONS_DIR = REPO_ROOT / "config" / "migrations"

_lock = asyncio.Lock()
_state: dict[str, aiosqlite.Connection | None] = {"conn": None}


async def _open() -> aiosqlite.Connection:
    settings = get_settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await aiosqlite.connect(settings.sqlite_path)
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA foreign_keys=ON")
    await conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = aiosqlite.Row
    return conn


async def get_connection() -> aiosqlite.Connection:
    """Return the process-wide aiosqlite connection, opening on first call."""
    if _state["conn"] is None:
        async with _lock:
            if _state["conn"] is None:
                opened = await _open()
                await _migrate(opened)
                _state["conn"] = opened
    conn = _state["conn"]
    assert conn is not None
    return conn


async def close() -> None:
    """Close the cached connection (idempotent)."""
    conn = _state["conn"]
    if conn is not None:
        await conn.close()
        _state["conn"] = None


@asynccontextmanager
async def transaction() -> AsyncIterator[aiosqlite.Connection]:
    """Yield the connection inside a transaction. Commits on success, rolls back on error."""
    conn = await get_connection()
    try:
        yield conn
        await conn.commit()
    except Exception:
        await conn.rollback()
        raise


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


async def _migrate(conn: aiosqlite.Connection) -> None:
    """Apply any pending SQL migrations from config/migrations/."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    await conn.commit()

    cur = await conn.execute("SELECT version FROM schema_version")
    rows = await cur.fetchall()
    applied = {r["version"] for r in rows}

    for path in _migration_files():
        version = int(path.stem.split("_")[0])
        if version in applied:
            continue
        log.info("migration.apply", version=version, file=path.name)
        sql = path.read_text(encoding="utf-8")
        await conn.executescript(sql)
        await conn.execute(
            "INSERT OR IGNORE INTO schema_version(version, applied_at) VALUES (?, ?)",
            (version, _now_iso()),
        )
        await conn.commit()


def _migration_files() -> list[Path]:
    if not MIGRATIONS_DIR.exists():
        return []
    return sorted(MIGRATIONS_DIR.glob("*.sql"))
