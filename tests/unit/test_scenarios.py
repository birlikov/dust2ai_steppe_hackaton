"""Tests for scenario loader + runner."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from src.scenarios.loader import Scenario, load_scenario, load_scenarios
from src.scenarios.runner import DispatcherReply, run_scenario


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_loads_minimal_scenario(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    _write_yaml(p, {"id": "s1", "workflow": 1, "turns": [{"user": "hi"}]})
    s = load_scenario(p)
    assert s.id == "s1"
    assert s.turns[0].user == "hi"


def test_load_scenarios_recurses(tmp_path: Path) -> None:
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_yaml(tmp_path / "a.yaml", {"id": "a", "workflow": 1})
    _write_yaml(sub / "b.yml", {"id": "b", "workflow": 2})
    found = load_scenarios(tmp_path)
    ids = {s.id for s in found}
    assert ids == {"a", "b"}


def test_unknown_field_rejected(tmp_path: Path) -> None:
    p = tmp_path / "s.yaml"
    _write_yaml(
        p,
        {"id": "s1", "workflow": 1, "turns": [{"user": "x", "expect": {"weird_key": True}}]},
    )
    with pytest.raises(ValueError):
        load_scenario(p)


async def test_runner_passes_when_text_matches() -> None:
    s = Scenario.model_validate(
        {
            "id": "s",
            "workflow": 1,
            "turns": [
                {"user": "hi", "expect": {"contains_any": ["hello"]}},
            ],
        }
    )

    async def dispatcher(user: str, state: dict) -> DispatcherReply:
        return DispatcherReply(text="hello there")

    result = await run_scenario(s, dispatcher)
    assert result.passed
    assert result.turns[0].failures == []


async def test_runner_flags_missing_tool_call() -> None:
    s = Scenario.model_validate(
        {
            "id": "s",
            "workflow": 1,
            "turns": [
                {"user": "hi", "expect": {"tool_calls_include": ["sandbox__lookup"]}},
            ],
        }
    )

    async def dispatcher(user: str, state: dict) -> DispatcherReply:
        return DispatcherReply(text="ok", tool_calls=[])

    result = await run_scenario(s, dispatcher)
    assert not result.passed
    assert any("missing tool call" in f for f in result.failures)


async def test_runner_tracks_tool_calls_across_turns() -> None:
    """A required tool call counts as satisfied even if it happens on an earlier turn."""
    s = Scenario.model_validate(
        {
            "id": "s",
            "workflow": 1,
            "turns": [
                {"user": "hi", "expect": {}},
                {"user": "next", "expect": {"tool_calls_include": ["x"]}},
            ],
        }
    )

    calls = iter([["x"], []])

    async def dispatcher(user: str, state: dict) -> DispatcherReply:
        return DispatcherReply(text="ok", tool_calls=next(calls))

    result = await run_scenario(s, dispatcher)
    assert result.passed
