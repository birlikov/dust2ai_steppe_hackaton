"""Telegram-flavour Markdown normalisation.

Telegram's classic Markdown parser uses **single** asterisks for bold
(``*bold*``) and underscores for italic (``_italic_``). The Anthropic
runtime persona, by training, prefers CommonMark — ``**bold**`` (double
asterisks) — which Telegram renders as **literal asterisks around
the word**, not bold.

This module is a small, deterministic string transform that:

  - converts ``**X**`` → ``*X*``
  - converts ``__X__`` → ``*X*`` (CommonMark double-underscore bold)
  - drops empty markdown links ``[text]()`` that Telegram errors on
  - leaves single ``*X*`` and ``_X_`` (already Telegram-correct) alone

Called from every bot reply path before ``message.answer(parse_mode="Markdown")``.
Pure string transform, no I/O, unit-tested.
"""

from __future__ import annotations

import re

_BOLD_DOUBLE_ASTERISK = re.compile(r"\*\*([^*\n]+?)\*\*")
_BOLD_DOUBLE_UNDERSCORE = re.compile(r"__([^_\n]+?)__")
_EMPTY_MARKDOWN_LINK = re.compile(r"\[([^\]]*)\]\(\s*\)")


def tg_normalise(text: str) -> str:
    """Return ``text`` with Telegram-classic Markdown bold syntax.

    Idempotent: running it twice returns the same string. Safe to apply
    to text already in Telegram-flavour Markdown.
    """
    if not text:
        return text
    out = _BOLD_DOUBLE_ASTERISK.sub(r"*\1*", text)
    out = _BOLD_DOUBLE_UNDERSCORE.sub(r"*\1*", out)
    out = _EMPTY_MARKDOWN_LINK.sub(r"\1", out)
    return out
