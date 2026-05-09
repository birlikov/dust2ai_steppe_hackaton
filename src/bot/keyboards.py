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
