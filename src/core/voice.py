"""Brand-voice linter — checks runtime-generated copy against the brandbook hard rules.

Used by:
  - the orchestrator (each outbound assistant reply is linted; warnings logged)
  - the drafts approval queue (post drafts must lint clean before reaching the
    owner — a lint failure regenerates the draft)
  - phase-4 polish sweep (manual scan over committed copy strings)

The linter is intentionally simple and fast: pure regex over the string. Hard
violations (wordmark, banned adjectives, too many emoji, non-English markers,
missing closing pattern when required) come out as :class:`Violation` records
with stable rule IDs (``brand.r1``..``brand.r12``). Soft violations (post is
longer than 1000 chars, etc.) are not enforced here — they live in the
agent's RULES.md self-check.

The linter never rewrites — it reports. Callers decide what to do.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

CLOSING_PATTERN: Final = (
    "Order on the site at happycake.us or send a message on WhatsApp."
)

ASCII_BOUNDARY = 0x80  # codepoints below this are plain ASCII
MAX_EMOJIS = 3  # brand.r4: ≤3 emojis per post


@dataclass(slots=True, frozen=True)
class Violation:
    """One brand-voice issue. ``rule_id`` ties back to ``docs/specs.md``."""

    rule_id: str
    message: str
    excerpt: str = ""


@dataclass(slots=True, frozen=True)
class LintRequest:
    """A single piece of copy to lint with optional contextual flags.

    ``require_closing_pattern`` is True for posts and CTAs (anywhere brand.r8
    applies); False for short DM replies where the channel makes the closing
    redundant.
    """

    text: str
    require_closing_pattern: bool = False
    channel: str = "generic"  # informational only; not enforced


# ---------------------------------------------------------------------------
# Wordmark — brand.r2
# ---------------------------------------------------------------------------
# Match misspellings without consuming the legitimate "HappyCake" form. Use
# negative lookahead/behind to avoid double-counting nested matches.

# "Happy Cake" with a separator (space, hyphen, NBSP) — never allowed.
_RE_WORDMARK_SPLIT = re.compile("\\bHappy[\u0020\u00a0\\-]Cake\\b", re.IGNORECASE)
# "HC" as a standalone token — but not when it's a real word like "achieve".
_RE_WORDMARK_HC = re.compile(r"(?<![A-Za-z0-9])HC(?![A-Za-z0-9])")
# All-caps "HAPPYCAKE".
_RE_WORDMARK_ALLCAPS = re.compile(r"\bHAPPYCAKE\b")
# All-lowercase "happycake" — but allow the URL ``happycake.us``/``happycake.com``.
_RE_WORDMARK_LOWER = re.compile(r"(?<![A-Za-z0-9])happycake(?![A-Za-z0-9.])")


# ---------------------------------------------------------------------------
# Cake names — brand.r3
# ---------------------------------------------------------------------------
# Catch the inverted form: "Honey cake" or "Napoleon cake". The legitimate form
# is `cake "Honey"` so we look for a capitalised cake name *before* the lowercase
# word "cake".
_KNOWN_CAKE_NAMES: tuple[str, ...] = (
    "Honey",
    "Napoleon",
    "Milk Maiden",
    "Pistachio Roll",
    "Tiramisu",
)
_RE_INVERTED_CAKE = re.compile(
    r"\b(?P<name>" + "|".join(re.escape(n) for n in _KNOWN_CAKE_NAMES) + r")\s+cake\b",
    re.IGNORECASE,
)

# Bare canonical name used as a noun ("a Napoleon", "the Tiramisu") without
# the `cake "X"` form. We exclude "Honey" from this list because lowercase
# "honey" is a generic noun (honey-baked, honey-glazed) and would over-flag.
_BARE_CAKE_NAMES: tuple[str, ...] = (
    "Napoleon",
    "Milk Maiden",
    "Pistachio Roll",
    "Tiramisu",
)
_RE_BARE_CAKE_NAME = re.compile(
    r'(?<!cake ")(?<![A-Za-z0-9])(?P<name>'
    + "|".join(re.escape(n) for n in _BARE_CAKE_NAMES)
    + r")(?![A-Za-z0-9])"
)


# ---------------------------------------------------------------------------
# Banned adjectives + ad clichés — brand.r10
# ---------------------------------------------------------------------------
_BANNED_ADJECTIVES: tuple[str, ...] = (
    "amazing",
    "awesome",
    "incredible",
    "unbelievable",
    "magical",
    "mouth-watering",
    "the best",
    "world-class",
    "absolutely",
    "extraordinary",
    "phenomenal",
    "spectacular",
    "stunning",
    "out of this world",
    "second to none",
)
_RE_BANNED_ADJECTIVES = re.compile(
    r"(?<![A-Za-z])(" + "|".join(re.escape(w) for w in _BANNED_ADJECTIVES) + r")(?![A-Za-z])",
    re.IGNORECASE,
)

# Ad clichés the brandbook explicitly bans (§2 examples + §7 voice rules).
_AD_CLICHES: tuple[str, ...] = (
    "BUY NOW",
    "buy now",
    "don't miss out",
    "dont miss out",
    "limited offer",
    "limited time only",
    "act now",
    "hurry",
    "exclusive offer",
    "best deal ever",
)
_RE_AD_CLICHES = re.compile(
    r"\b(" + "|".join(re.escape(p) for p in _AD_CLICHES) + r")!*",
    re.IGNORECASE,
)

# Brandbook §2 — informal openings forbidden.
_RE_INFORMAL_GREETING = re.compile(
    r"\b(hey guys|yo guys|sup guys|what'?s up guys)\b", re.IGNORECASE
)

# Excessive exclamation (brandbook §2: "Order our amazing cakes today!!!" is
# the canonical bad example). Three or more in a row is a hard signal.
_RE_EXCLAMATION_TRIPLE = re.compile(r"!{3,}")


# ---------------------------------------------------------------------------
# Emoji count — brand.r4 (≤3)
# ---------------------------------------------------------------------------
def _count_emojis(text: str) -> int:
    """Count Unicode codepoints in symbol categories the brandbook treats as emoji."""
    count = 0
    for ch in text:
        if ord(ch) < ASCII_BOUNDARY:
            continue
        cat = unicodedata.category(ch)
        # So = Other Symbol (most pictographic emoji); Sk = Modifier Symbol;
        # Sm = Math Symbol (excluded). Cs = Surrogate (count once).
        if cat in {"So", "Sk"}:
            count += 1
    return count


# ---------------------------------------------------------------------------
# Non-English markers — brand.r1
# ---------------------------------------------------------------------------
# Cyrillic and Hangul/CJK run blocks. We don't pretend to detect every language;
# we flag obvious cases of non-English content.
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_RE_CJK = re.compile(r"[぀-ヿ一-鿿]")


def lint(request: LintRequest) -> list[Violation]:
    """Run all checks and return zero or more :class:`Violation` records."""
    text = request.text
    violations: list[Violation] = []

    # brand.r1 — English only
    if _RE_CYRILLIC.search(text):
        violations.append(
            Violation(
                rule_id="brand.r1",
                message="Non-English text (Cyrillic) detected; reply must be English.",
                excerpt=_first_match(_RE_CYRILLIC, text),
            )
        )
    if _RE_CJK.search(text):
        violations.append(
            Violation(
                rule_id="brand.r1",
                message="Non-English text (CJK) detected; reply must be English.",
                excerpt=_first_match(_RE_CJK, text),
            )
        )

    # brand.r2 — wordmark
    for pattern, msg in (
        (_RE_WORDMARK_SPLIT, 'wordmark split — use "HappyCake", not "Happy Cake".'),
        (_RE_WORDMARK_HC, 'abbreviated wordmark "HC" — use "HappyCake".'),
        (_RE_WORDMARK_ALLCAPS, 'all-caps wordmark — use "HappyCake", not "HAPPYCAKE".'),
        (_RE_WORDMARK_LOWER, 'lowercase wordmark — use "HappyCake", not "happycake".'),
    ):
        m = pattern.search(text)
        if m:
            violations.append(
                Violation(rule_id="brand.r2", message=msg, excerpt=m.group(0))
            )

    # brand.r3 — cake names (inverted form: "Honey cake" → cake "Honey")
    m = _RE_INVERTED_CAKE.search(text)
    if m:
        violations.append(
            Violation(
                rule_id="brand.r3",
                message=(
                    f'cake name placement — use cake "{m.group("name")}" '
                    f"instead of \"{m.group('name')} cake\"."
                ),
                excerpt=m.group(0),
            )
        )
    # brand.r3 — bare canonical names used as nouns ("a Napoleon")
    m_bare = _RE_BARE_CAKE_NAME.search(text)
    if m_bare:
        violations.append(
            Violation(
                rule_id="brand.r3",
                message=(
                    f'bare cake name — use cake "{m_bare.group("name")}" '
                    f"with the wordmark prefix."
                ),
                excerpt=m_bare.group(0),
            )
        )

    # brand.r4 — emoji count
    emojis = _count_emojis(text)
    if emojis > MAX_EMOJIS:
        violations.append(
            Violation(
                rule_id="brand.r4",
                message=(
                    f"emoji count {emojis} exceeds the "
                    f"{MAX_EMOJIS}-per-post maximum."
                ),
            )
        )

    # brand.r10 — voice / banned adjectives + ad clichés
    for m_adj in _RE_BANNED_ADJECTIVES.finditer(text):
        violations.append(
            Violation(
                rule_id="brand.r10",
                message=f'banned adjective "{m_adj.group(0)}" — pick a specific fact instead.',
                excerpt=m_adj.group(0),
            )
        )
    m_cliche = _RE_AD_CLICHES.search(text)
    if m_cliche:
        violations.append(
            Violation(
                rule_id="brand.r10",
                message=(
                    "ad cliché — close with the closing pattern, "
                    "not BUY NOW / limited-offer language."
                ),
                excerpt=m_cliche.group(0),
            )
        )

    m_greet = _RE_INFORMAL_GREETING.search(text)
    if m_greet:
        violations.append(
            Violation(
                rule_id="brand.r10",
                message=(
                    'informal opening "hey guys" — open with '
                    '"Good morning, friends." or "Hi, <name>." (brandbook §2).'
                ),
                excerpt=m_greet.group(0),
            )
        )

    m_excl = _RE_EXCLAMATION_TRIPLE.search(text)
    if m_excl:
        violations.append(
            Violation(
                rule_id="brand.r10",
                message="excessive exclamation — at most one '!' per sentence (brandbook §2).",
                excerpt=m_excl.group(0),
            )
        )

    # brand.r8 — closing pattern (only when caller asks for it)
    if request.require_closing_pattern and CLOSING_PATTERN not in text:
        violations.append(
            Violation(
                rule_id="brand.r8",
                message=(
                    "missing closing pattern — append "
                    f'"{CLOSING_PATTERN}".'
                ),
            )
        )

    return violations


def lint_text(
    text: str, *, require_closing_pattern: bool = False, channel: str = "generic"
) -> list[Violation]:
    """Convenience wrapper for callers that don't want to build a request struct."""
    return lint(
        LintRequest(
            text=text,
            require_closing_pattern=require_closing_pattern,
            channel=channel,
        )
    )


def _first_match(pattern: re.Pattern[str], text: str) -> str:
    m = pattern.search(text)
    return m.group(0) if m else ""


def is_clean(violations: Iterable[Violation]) -> bool:
    """Return True if no violations were reported."""
    return not any(True for _ in violations)
