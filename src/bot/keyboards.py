"""Inline-keyboard builders for the owner-facing Telegram bot."""

from __future__ import annotations

import math
from datetime import UTC, datetime

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


# ---------------------------------------------------------------------------
# /refund — inline order picker
# ---------------------------------------------------------------------------

CB_REFUND_PICK_PREFIX = "refund:pick:"

# Telegram caps callback_data at 64 bytes.
# "refund:pick:" is 12 bytes, leaving 52 bytes for the order id.
# Simulator ids look like "sq_order_1778416371695" (22 chars) — well within
# 52, so we use the full id directly without any truncation map.
_REFUND_CB_ORDER_MAX = 52

# Time thresholds for human-relative formatting (seconds).
_SECS_JUST_NOW = 90
_SECS_HOUR = 3600
_SECS_DAY = 86400
# Dollar threshold: if total_raw looks like cents (> this), divide by 100.
_DOLLAR_CENTS_THRESHOLD = 10_000


def _human_relative_time(iso: str) -> str:
    """Return a short human-relative label: '8h ago', '12m ago', 'just now'.

    Tolerates missing or malformed ISO strings — returns '' instead of raising.
    """
    if not iso:
        return ""
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - ts
        total_seconds = delta.total_seconds()
        if total_seconds < _SECS_JUST_NOW:
            return "just now"
        if total_seconds < _SECS_HOUR:
            mins = math.floor(total_seconds / 60)
            return f"{mins}m ago"
        if total_seconds < _SECS_DAY:
            hours = math.floor(total_seconds / _SECS_HOUR)
            return f"{hours}h ago"
        days = math.floor(total_seconds / _SECS_DAY)
        return f"{days}d ago"
    except (ValueError, TypeError, OverflowError):
        return ""


def _order_button_label(order: dict[str, object]) -> str:
    """Build the human-readable button label for one order row."""
    customer = str(order.get("customerName") or order.get("customer") or "?")
    # Items may be a list of dicts with slug/name, or a plain list of strings.
    items = order.get("items") or []
    first_slug = ""
    if isinstance(items, list) and items:
        first = items[0]
        if isinstance(first, dict):
            first_slug = str(first.get("slug") or first.get("name") or "")
        elif isinstance(first, str):
            first_slug = first
    # Trim slug to keep button label concise.
    slug_short = first_slug[:20] if first_slug else "?"
    # Total — prefer cents → dollars conversion if "totalMoney" is a dict.
    total_raw = order.get("totalMoney") or order.get("total") or order.get("amount")
    total_str = "?"
    if isinstance(total_raw, dict):
        cents = total_raw.get("amount")
        if isinstance(cents, (int, float)) and cents > 0:
            total_str = f"${cents / 100:.2f}"
    elif isinstance(total_raw, (int, float)) and total_raw > 0:
        # If value looks like cents (> threshold), divide by 100; else treat as dollars.
        total_str = (
            f"${total_raw / 100:.2f}"
            if total_raw >= _DOLLAR_CENTS_THRESHOLD
            else f"${total_raw:.2f}"
        )
    # Timestamp.
    iso = str(order.get("createdAt") or order.get("ts") or "")
    rel = _human_relative_time(iso)
    rel_part = f" · {rel}" if rel else ""
    return f"{customer[:20]} — {slug_short} · {total_str}{rel_part}"


def refund_picker_keyboard(orders: list[dict[str, object]]) -> InlineKeyboardMarkup:
    """One button per row for up to 10 orders in the refund picker.

    Use when: the owner taps bare /refund with no order id.
    Each button's callback_data is ``refund:pick:<order_id>`` (≤64 bytes total).
    """
    rows: list[list[InlineKeyboardButton]] = []
    for order in orders:
        order_id = str(order.get("id") or order.get("orderId") or "")
        if not order_id:
            continue
        # Truncate the id portion only if it would overflow the 64-byte cap.
        id_part = order_id[:_REFUND_CB_ORDER_MAX]
        cb = f"{CB_REFUND_PICK_PREFIX}{id_part}"
        label = _order_button_label(order)
        rows.append(
            [InlineKeyboardButton(text=label, callback_data=cb)]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def parse_refund_callback(data: str) -> str:
    """Decode a ``refund:pick:<order_id>`` callback into ``order_id``.

    Returns:
        The order id string (non-empty).

    Raises:
        ValueError: for any malformed or non-refund callback.
    """
    if not data.startswith(CB_REFUND_PICK_PREFIX):
        raise ValueError(f"not a refund:pick callback: {data!r}")
    order_id = data[len(CB_REFUND_PICK_PREFIX):]
    if not order_id:
        raise ValueError(f"empty order_id in refund callback: {data!r}")
    return order_id


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
