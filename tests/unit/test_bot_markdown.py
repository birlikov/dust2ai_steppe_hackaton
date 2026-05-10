from __future__ import annotations

from src.bot.markdown import tg_normalise


def test_double_asterisk_bold_normalised() -> None:
    assert tg_normalise("**Heads up:** 4 drafts") == "*Heads up:* 4 drafts"


def test_double_underscore_bold_normalised() -> None:
    assert tg_normalise("__important__ note") == "*important* note"


def test_single_asterisk_left_alone() -> None:
    # Single-asterisk is Telegram-classic bold; leave unchanged.
    assert tg_normalise("*already bold*") == "*already bold*"


def test_single_underscore_italic_left_alone() -> None:
    assert tg_normalise("_italic_") == "_italic_"


def test_empty_link_text_preserved() -> None:
    # Empty URL would 400 Telegram; we strip the parens but keep the text.
    assert tg_normalise("see [the docs]()") == "see the docs"


def test_idempotent() -> None:
    once = tg_normalise("**A** and *B* and __C__")
    twice = tg_normalise(once)
    assert once == twice
    assert "**" not in once
    assert "__" not in once


def test_empty_input() -> None:
    assert tg_normalise("") == ""


def test_mixed_content() -> None:
    src = "📊 **Six orders**, *$142 net*. _Two_ on **WhatsApp**."
    out = tg_normalise(src)
    assert out == "📊 *Six orders*, *$142 net*. _Two_ on *WhatsApp*."
