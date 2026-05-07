"""Model tier mapping. Default cheap, promote on observed gaps."""

from __future__ import annotations

from enum import StrEnum


class Tier(StrEnum):
    CHEAP = "cheap"
    DEFAULT = "default"
    HEAVY = "heavy"


MODEL_BY_TIER: dict[Tier, str] = {
    Tier.CHEAP: "claude-haiku-4-5",
    Tier.DEFAULT: "claude-sonnet-4-6",
    Tier.HEAVY: "claude-opus-4-7",
}


def model_for(tier: Tier | str) -> str:
    if isinstance(tier, str):
        tier = Tier(tier)
    return MODEL_BY_TIER[tier]
