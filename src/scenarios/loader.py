"""Scenario YAML schema + loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field


class TurnExpect(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contains_any: list[str] = Field(default_factory=list)
    contains_all: list[str] = Field(default_factory=list)
    not_contains: list[str] = Field(default_factory=list)
    tool_calls_include: list[str] = Field(default_factory=list)
    final_state: str | None = None


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user: str
    expect: TurnExpect = Field(default_factory=TurnExpect)


class PostCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    db_state: dict[str, Any] | None = None


class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    workflow: int | str
    description: str = ""
    turns: list[Turn] = Field(default_factory=list)
    post: PostCondition | None = None


def load_scenario(path: Path) -> Scenario:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Scenario.model_validate(raw)


def load_scenarios(directory: Path) -> list[Scenario]:
    """Load every *.yaml/*.yml in `directory` (recursive)."""
    found: list[Scenario] = []
    for ext in ("*.yaml", "*.yml"):
        for path in sorted(directory.rglob(ext)):
            found.append(load_scenario(path))
    return found
