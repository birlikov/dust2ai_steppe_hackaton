"""Run every scenario in a directory and write scorecard.json.

Usage:
    uv run python scripts/run_scenarios.py tests/scenarios/

Until the live dispatcher is wired in, this uses a deterministic stub that
echoes the turn — useful for validating the harness itself.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow `from src.*` imports when running this file directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scenarios.loader import load_scenarios
from src.scenarios.runner import (
    DispatcherReply,
    ScenarioResult,
    run_scenario,
    summarize,
)


async def _stub_dispatcher(user: str, state: dict[str, Any]) -> DispatcherReply:
    """Echo dispatcher used for harness self-tests. Replace with live agent loop."""
    state.setdefault("history", []).append(user)
    return DispatcherReply(text=f"[stub] {user}")


async def _amain(directory: Path, out: Path) -> int:
    scenarios = load_scenarios(directory)
    if not scenarios:
        print(f"No scenarios in {directory}", file=sys.stderr)
        return 1

    results: list[ScenarioResult] = []
    for s in scenarios:
        results.append(await run_scenario(s, _stub_dispatcher))

    report = summarize(results)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], indent=2))
    return 0 if report["summary"]["failed"] == 0 else 1


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: run_scenarios.py <scenarios_dir> [out_path]", file=sys.stderr)
        sys.exit(2)
    directory = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("scorecard.json")
    code = asyncio.run(_amain(directory, out))
    sys.exit(code)


if __name__ == "__main__":
    main()
