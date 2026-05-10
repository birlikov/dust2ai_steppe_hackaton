"""Inline-keyboard builders for the owner-facing Telegram bot."""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Callback data shapes are short — Telegram caps them at 64 bytes.
CB_APPROVE = "draft:approve:{id}"
CB_REJECT = "draft:reject:{id}"
CB_EDIT = "draft:edit:{id}"


def draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    """Approve / Reject / Edit row for a single draft preview."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Approve",
                    callback_data=CB_APPROVE.format(id=draft_id),
                ),
                InlineKeyboardButton(
                    text="📝 Edit",
                    callback_data=CB_EDIT.format(id=draft_id),
                ),
                InlineKeyboardButton(
                    text="❌ Reject",
                    callback_data=CB_REJECT.format(id=draft_id),
                ),
            ]
        ]
    )


def parse_draft_callback(data: str) -> tuple[str, str] | None:
    """Return ``(action, draft_id)`` from a callback string, or ``None``."""
    parts = data.split(":")
    expected_parts = 3
    if len(parts) != expected_parts or parts[0] != "draft":
        return None
    action = parts[1]
    if action not in {"approve", "reject", "edit"}:
        return None
    return action, parts[2]


# ---------------------------------------------------------------------------
# /notify — inline picker (presets the owner can tap)
# ---------------------------------------------------------------------------

CB_NOTIFY_PREFIX = "notify:"

# (label, seconds-or-None). ``None`` means "clear the per-owner override" so
# the notifier falls back to whatever NOTIFIER_INTERVAL_S is in `.env`
# (default 1800 = 30 min).
NOTIFY_OPTIONS: tuple[tuple[str, int | None], ...] = (
    ("1 min", 60),
    ("30 min", 1800),
    ("2 h", 7200),
    ("Off", 0),
    ("Default", None),
)


def notify_keyboard(current_seconds: int | None) -> InlineKeyboardMarkup:
    """Inline picker for the proactive-push cadence.

    ``current_seconds`` is the per-owner override (``None`` if no
    override — the bot uses the env default). The matching option is
    prefixed with ``✓``.
    """
    rows: list[list[InlineKeyboardButton]] = [[], []]
    for label, secs in NOTIFY_OPTIONS:
        is_current = secs == current_seconds
        prefix = "✓ " if is_current else ""
        cb_value = "default" if secs is None else str(secs)
        button = InlineKeyboardButton(
            text=f"{prefix}{label}",
            callback_data=f"{CB_NOTIFY_PREFIX}{cb_value}",
        )
        # First three on row 0, last two on row 1 — fits Telegram nicely.
        first_row_max = 3
        target = rows[0] if len(rows[0]) < first_row_max else rows[1]
        target.append(button)
    return InlineKeyboardMarkup(inline_keyboard=rows)


_NOTIFY_INVALID = object()


def parse_notify_callback(data: str) -> int | None:
    """Decode a ``notify:<value>`` callback into ``seconds`` or ``None``.

    Returns:
        - an integer ``>= 0`` (``0`` = silenced) for an explicit interval, or
        - ``None`` for the "Default" choice (clear the per-owner override).

    Raises ``ValueError`` for any unparseable value — call sites can
    treat that as a stale or malformed callback.
    """
    if not data.startswith(CB_NOTIFY_PREFIX):
        raise ValueError(f"not a notify callback: {data!r}")
    val = data[len(CB_NOTIFY_PREFIX) :]
    if val == "default":
        return None
    try:
        seconds = int(val)
    except ValueError as exc:
        raise ValueError(f"bad notify seconds: {val!r}") from exc
    if seconds < 0:
        raise ValueError(f"negative notify seconds: {seconds}")
    return seconds
