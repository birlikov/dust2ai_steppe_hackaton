from __future__ import annotations

import pytest
from src.core.voice import CLOSING_PATTERN, LintRequest, lint, lint_text


def test_clean_text_yields_no_violations() -> None:
    text = (
        'Today\'s bake is out. The cake "Honey" is on the counter — 1.2 kg, $42, '
        f"ready through Sunday. {CLOSING_PATTERN}"
    )
    assert lint_text(text, require_closing_pattern=True) == []


def test_split_wordmark_flagged() -> None:
    violations = lint_text("Welcome to Happy Cake Sugar Land.")
    rule_ids = [v.rule_id for v in violations]
    assert "brand.r2" in rule_ids


def test_lowercase_wordmark_flagged_but_url_allowed() -> None:
    text = "Order on the site at happycake.us — happycake is fresh today."
    rule_ids = [v.rule_id for v in lint_text(text)]
    assert "brand.r2" in rule_ids
    # Just one violation — the URL form should not also fire.
    assert rule_ids.count("brand.r2") == 1


def test_allcaps_wordmark_flagged() -> None:
    violations = lint_text("HAPPYCAKE has a new flavor.")
    assert any(v.rule_id == "brand.r2" for v in violations)


def test_hc_abbreviation_flagged_but_real_words_safe() -> None:
    bad = lint_text("HC is back!")
    good = lint_text("We honour the recipe and the achievement.")
    assert any(v.rule_id == "brand.r2" for v in bad)
    assert all(v.rule_id != "brand.r2" for v in good)


def test_inverted_cake_name_flagged() -> None:
    violations = lint_text("Napoleon cake is the favourite this week.")
    assert any(v.rule_id == "brand.r3" for v in violations)


def test_correct_cake_name_form_clean() -> None:
    violations = lint_text('Try our cake "Napoleon" today — 1.2 kg, $40.')
    assert all(v.rule_id != "brand.r3" for v in violations)


@pytest.mark.parametrize(
    "text",
    [
        "We have honey cake today.",
        "the whole honey cake is $55.",
        "tiramisu cake is back this week.",
        "PISTACHIO ROLL CAKE FOR SALE",
    ],
)
def test_inverted_cake_name_case_insensitive(text: str) -> None:
    """Lowercase / mixed-case inverted forms must trip brand.r3."""
    rules = {v.rule_id for v in lint_text(text)}
    assert "brand.r3" in rules


@pytest.mark.parametrize(
    "text",
    [
        "Recommend a Napoleon for celebrations.",
        "the Tiramisu is light and airy.",
        "Bring back the Pistachio Roll, please.",
    ],
)
def test_bare_cake_name_flagged(text: str) -> None:
    """Bare canonical names used as nouns must trip brand.r3."""
    rules = {v.rule_id for v in lint_text(text)}
    assert "brand.r3" in rules


@pytest.mark.parametrize(
    "text",
    [
        'Try our cake "Napoleon" today — 1.2 kg, $40.',
        'cake "Pistachio Roll" is on the counter.',
        "Honey-glazed walnuts dust the top.",  # lowercase "honey" is fine on its own
    ],
)
def test_canonical_cake_form_does_not_flag(text: str) -> None:
    rules = {v.rule_id for v in lint_text(text)}
    assert "brand.r3" not in rules


def test_too_many_emoji_flagged() -> None:
    text = "Today's bake 🎂🎂🎂🎂 is fresh."  # four cake emojis
    rule_ids = [v.rule_id for v in lint_text(text)]
    assert "brand.r4" in rule_ids


def test_banned_adjective_flagged() -> None:
    violations = lint_text("Our amazing cake is back.")
    rule_ids = [v.rule_id for v in violations]
    assert "brand.r10" in rule_ids


def test_buy_now_flagged() -> None:
    violations = lint_text("BUY NOW! Limited offer this weekend!")
    rule_ids = [v.rule_id for v in violations]
    assert rule_ids.count("brand.r10") >= 1


def test_extended_banned_list_flagged() -> None:
    violations = lint_text("Our extraordinary, phenomenal honey cake!")
    msgs = " ".join(v.message for v in violations)
    assert "extraordinary" in msgs.lower() or "phenomenal" in msgs.lower()


def test_informal_greeting_flagged() -> None:
    violations = lint_text("Hey guys, what's up — order our cake today.")
    rule_ids = [v.rule_id for v in violations]
    assert "brand.r10" in rule_ids


def test_excessive_exclamation_flagged() -> None:
    violations = lint_text('Cake "Honey" is back!!!')
    rule_ids = [v.rule_id for v in violations]
    assert "brand.r10" in rule_ids


def test_act_now_hurry_flagged() -> None:
    violations = lint_text("Act now! Hurry — exclusive offer ends Sunday.")
    rule_ids = [v.rule_id for v in violations]
    assert rule_ids.count("brand.r10") >= 1


def test_cyrillic_flagged() -> None:
    violations = lint_text("Привет, у нас новый торт.")  # noqa: RUF001
    assert any(v.rule_id == "brand.r1" for v in violations)


def test_missing_closing_pattern_flagged_when_required() -> None:
    text = 'Cake "Honey" — 1.2 kg, $42.'
    violations = lint(LintRequest(text=text, require_closing_pattern=True))
    assert any(v.rule_id == "brand.r8" for v in violations)


def test_closing_pattern_not_required_for_dm_reply() -> None:
    text = 'Yes — cake "Honey" is on the counter, 1.2 kg, $42.'
    violations = lint(LintRequest(text=text, require_closing_pattern=False))
    assert all(v.rule_id != "brand.r8" for v in violations)
