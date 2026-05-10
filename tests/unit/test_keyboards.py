"""Inline-keyboard helpers — draft + notify."""

from __future__ import annotations

import pytest
from src.bot.keyboards import (
    NOTIFY_OPTIONS,
    notify_keyboard,
    parse_draft_callback,
    parse_notify_callback,
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
