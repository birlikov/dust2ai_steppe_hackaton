"""Inline-keyboard helpers — draft + notify + refund."""

from __future__ import annotations

import pytest
from src.bot.keyboards import (
    NOTIFY_OPTIONS,
    notify_keyboard,
    parse_draft_callback,
    parse_notify_callback,
    parse_refund_callback,
    refund_picker_keyboard,
)


def test_parse_draft_callback_roundtrip() -> None:
    assert parse_draft_callback("draft:approve:abc123") == ("approve", "abc123")
    assert parse_draft_callback("draft:reject:xyz") == ("reject", "xyz")
    assert parse_draft_callback("draft:edit:42") == ("edit", "42")


def test_parse_draft_callback_rejects_garbage() -> None:
    assert parse_draft_callback("notdraft:approve:1") is None
    assert parse_draft_callback("draft:bogus:1") is None
    assert parse_draft_callback("draft:approve") is None


@pytest.mark.parametrize(
    "data,expected",
    [
        ("notify:60", 60),
        ("notify:1800", 1800),
        ("notify:7200", 7200),
        ("notify:0", 0),
        ("notify:default", None),
    ],
)
def test_parse_notify_callback_known_values(
    data: str, expected: int | None
) -> None:
    assert parse_notify_callback(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        "notify:abc",
        "notify:-30",
        "draft:approve:1",
        "",
    ],
)
def test_parse_notify_callback_invalid(data: str) -> None:
    with pytest.raises(ValueError):
        parse_notify_callback(data)


def test_notify_keyboard_marks_current_30m() -> None:
    kb = notify_keyboard(1800)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    # Exactly one ✓ and it's on the 30 min row.
    assert sum(1 for label in labels if label.startswith("✓ ")) == 1
    assert any(label == "✓ 30 min" for label in labels)


def test_notify_keyboard_marks_default_when_no_override() -> None:
    kb = notify_keyboard(None)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert any(label == "✓ Default" for label in labels)
    # All five preset labels render.
    expected = {label for label, _ in NOTIFY_OPTIONS}
    rendered = {label.removeprefix("✓ ").strip() for label in labels}
    assert expected.issubset(rendered)


def test_notify_keyboard_callback_data_decodes() -> None:
    """Every button's callback_data round-trips through parse_notify_callback."""
    kb = notify_keyboard(60)
    for row in kb.inline_keyboard:
        for button in row:
            cb = button.callback_data or ""
            # Should not raise.
            parse_notify_callback(cb)


# ---------------------------------------------------------------------------
# refund:pick callbacks
# ---------------------------------------------------------------------------


def test_parse_refund_callback_roundtrip() -> None:
    """Standard simulator order id parses cleanly."""
    order_id = "sq_order_1778416371695"
    data = f"refund:pick:{order_id}"
    assert parse_refund_callback(data) == order_id


def test_parse_refund_callback_short_id() -> None:
    """Short or arbitrary ids also parse."""
    assert parse_refund_callback("refund:pick:abc123") == "abc123"


def test_parse_refund_callback_invalid_prefix() -> None:
    """Wrong prefix raises ValueError."""
    with pytest.raises(ValueError):
        parse_refund_callback("draft:approve:abc")


def test_parse_refund_callback_empty_order_id() -> None:
    """Bare prefix with no order id raises ValueError."""
    with pytest.raises(ValueError):
        parse_refund_callback("refund:pick:")


def test_parse_refund_callback_completely_wrong() -> None:
    """Totally unrelated string raises ValueError."""
    with pytest.raises(ValueError):
        parse_refund_callback("notify:60")


def test_refund_picker_keyboard_one_row_per_order() -> None:
    """Each order maps to exactly one button row."""
    orders: list[dict[str, object]] = [
        {"id": "sq_order_111", "customerName": "Alice"},
        {"id": "sq_order_222", "customerName": "Bob"},
    ]
    kb = refund_picker_keyboard(orders)
    assert len(kb.inline_keyboard) == 2
    for row in kb.inline_keyboard:
        assert len(row) == 1


def test_refund_picker_keyboard_callback_data_roundtrips() -> None:
    """Every button's callback_data decodes back to its order_id."""
    orders: list[dict[str, object]] = [
        {"id": "sq_order_abc", "customerName": "Carol"},
        {"id": "sq_order_xyz", "customerName": "Dan"},
    ]
    kb = refund_picker_keyboard(orders)
    order_ids = [str(o["id"]) for o in orders]
    for row, expected_id in zip(kb.inline_keyboard, order_ids, strict=True):
        cb = row[0].callback_data or ""
        assert parse_refund_callback(cb) == expected_id


def test_refund_picker_keyboard_skips_orders_without_id() -> None:
    """Orders missing both 'id' and 'orderId' are silently skipped."""
    orders: list[dict[str, object]] = [
        {"customerName": "Ghost"},  # no id field
        {"id": "sq_order_real", "customerName": "Real"},
    ]
    kb = refund_picker_keyboard(orders)
    assert len(kb.inline_keyboard) == 1
