"""Scenario runner.

Drives a Scenario through a pluggable dispatcher. The dispatcher is any async
callable taking a user message + per-conversation state and returning a
ScenarioReply (text + observed tool calls + optional final FSM state).

This abstraction keeps the harness testable without a live LLM and lets the
same runner drive both the dry-run and the live-agent paths.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from src.scenarios.loader import Scenario


@dataclass(slots=True)
class DispatcherReply:
    text: str
    tool_calls: list[str] = field(default_factory=list)
    final_state: str | None = None


Dispatcher = Callable[[str, dict[str, Any]], Awaitable[DispatcherReply]]


@dataclass(slots=True)
class TurnResult:
    index: int
    user: str
    reply_text: str
    tool_calls: list[str]
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(slots=True)
class ScenarioResult:
    scenario_id: str
    workflow: int | str
    description: str
    turns: list[TurnResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(t.passed for t in self.turns)

    @property
    def failures(self) -> list[str]:
        return [f for t in self.turns for f in t.failures]


async def run_scenario(scenario: Scenario, dispatcher: Dispatcher) -> ScenarioResult:
    state: dict[str, Any] = {"history": []}
    result = ScenarioResult(
        scenario_id=scenario.id,
        workflow=scenario.workflow,
        description=scenario.description,
    )
    tool_calls_seen: list[str] = []

    for index, turn in enumerate(scenario.turns):
        reply = await dispatcher(turn.user, state)
        tool_calls_seen.extend(reply.tool_calls)

        failures: list[str] = []
        ex = turn.expect
        if ex.contains_any and not any(s.lower() in reply.text.lower() for s in ex.contains_any):
            failures.append(f"text missing any-of {ex.contains_any!r}")
        for s in ex.contains_all:
            if s.lower() not in reply.text.lower():
                failures.append(f"text missing required {s!r}")
        for s in ex.not_contains:
            if s.lower() in reply.text.lower():
                failures.append(f"text unexpectedly contained {s!r}")
        for required in ex.tool_calls_include:
            if required not in tool_calls_seen:
                failures.append(f"missing tool call {required!r}")
        if ex.final_state is not None and reply.final_state != ex.final_state:
            failures.append(f"final_state expected {ex.final_state!r}, got {reply.final_state!r}")

        result.turns.append(
            TurnResult(
                index=index,
                user=turn.user,
                reply_text=reply.text,
                tool_calls=reply.tool_calls,
                failures=failures,
            )
        )

    return result


def summarize(results: list[ScenarioResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    return {
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "pct": f"{(passed / total * 100):.1f}" if total else "0.0",
        },
        "scenarios": [
            {
                "id": r.scenario_id,
                "workflow": r.workflow,
                "passed": r.passed,
                "turns": [
                    {
                        "index": t.index,
                        "user": t.user,
                        "reply": t.reply_text,
                        "tool_calls": t.tool_calls,
                        "failures": t.failures,
                    }
                    for t in r.turns
                ],
            }
            for r in results
        ],
    }
