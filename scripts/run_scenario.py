"""Drive a world-engine scenario end-to-end against the live MCP server.

Usage::

    uv run python scripts/run_scenario.py [--scenario launch-day-revenue-engine]
                                          [--max-events 60]
                                          [--advance-each 30]

The script:

  1. Connects to the happycake MCP server using ``SBC_TEAM_TOKEN``.
  2. Calls ``world_start_scenario`` (idempotent — restarts the scenario).
  3. Drains events with :class:`WorldPoller` while periodically calling
     ``world_advance_time`` so we don't wait real-world minutes.
  4. Pulls a final ``evaluator_score_world_scenario`` +
     ``evaluator_get_evidence_summary`` and writes them to
     ``data/scorecard_<timestamp>.json``.

Make sure the bridge can reach the ``claude`` CLI before running; the
poller relies on the orchestrator and the orchestrator drives ``claude
-p``. If the CLI is unavailable, the run still completes — replies just
become ``(no response)`` placeholders, but the audit + scoring path is
exercised end-to-end.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.agents.claude_bridge import build_default_bridge  # noqa: E402
from src.core.config import get_settings  # noqa: E402
from src.core.logging import get_logger  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)
from src.workflows.orchestrator import Orchestrator  # noqa: E402
from src.world.poller import WorldPoller  # noqa: E402

log = get_logger(__name__)


async def _amain(scenario_id: str, max_events: int, advance_each: int) -> int:
    settings = get_settings()
    out_dir = settings.sqlite_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        bridge = build_default_bridge()
    except Exception as exc:  # pragma: no cover
        print(f"bridge boot failed: {exc}", file=sys.stderr)
        return 2

    async with build_default_client() as mcp:
        # 1. Start (or restart) the scenario.
        try:
            start = await call_with_retry(
                mcp, "world_start_scenario", {"scenarioId": scenario_id}
            )
        except (McpTransportError, McpError) as exc:
            print(f"world_start_scenario failed: {exc}", file=sys.stderr)
            return 3
        log.info("world.scenario_started", scenario=scenario_id)
        print(f"started scenario {scenario_id!r}: {_short(start)}")

        # 2. Drain events.
        orchestrator = Orchestrator(bridge=bridge)
        poller = WorldPoller(
            mcp=mcp,
            orchestrator=orchestrator,
            max_events=max_events,
        )

        async def _advance() -> None:
            try:
                await call_with_retry(
                    mcp, "world_advance_time", {"minutes": advance_each}
                )
            except (McpTransportError, McpError) as exc:
                log.warning("world.advance_time_failed", err=str(exc))

        # Run the poller in chunks: advance time, drain a batch, repeat.
        events_processed = 0
        finished = False
        chunk_size = 10
        while events_processed < max_events and not finished:
            await _advance()
            poller.max_events = chunk_size
            chunk = await poller.run()
            events_processed += chunk.events_processed
            finished = chunk.finished
            if chunk.events_processed == 0 and not finished:
                # Scenario delivered nothing in this advance window; bail to
                # avoid spinning when the simulator is idle.
                break

        print(f"drained {events_processed} event(s); finished={finished}")

        # 3. Score + evidence.
        report: dict[str, object] = {
            "scenario": scenario_id,
            "started": _short(start),
            "events_processed": events_processed,
            "finished": finished,
            "ranAt": datetime.now(UTC).isoformat(),
        }
        for tool in (
            "evaluator_score_world_scenario",
            "evaluator_score_pos_kitchen_flow",
            "evaluator_score_channel_response",
            "evaluator_score_marketing_loop",
            "evaluator_get_evidence_summary",
        ):
            try:
                report[tool] = await call_with_retry(mcp, tool, {})
            except (McpTransportError, McpError) as exc:
                report[tool] = {"error": str(exc)}

    # 4. Persist scorecard.
    out_path = (
        out_dir
        / f"scorecard_{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"scorecard → {out_path.relative_to(REPO_ROOT)}")
    print(json.dumps(_short(report), indent=2))
    return 0


def _short(value: object) -> object:
    """Trim large nested objects for terminal-friendly prints."""
    if isinstance(value, dict):
        return {k: _short(v) for k, v in list(value.items())[:8]}
    if isinstance(value, list):
        return [_short(v) for v in value[:5]]
    if isinstance(value, str):
        max_len = 200
        return value if len(value) < max_len else value[:max_len] + "…"
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scenario", default="launch-day-revenue-engine"
    )
    parser.add_argument("--max-events", type=int, default=60)
    parser.add_argument("--advance-each", type=int, default=30)
    args = parser.parse_args()
    sys.exit(
        asyncio.run(
            _amain(args.scenario, args.max_events, args.advance_each)
        )
    )


if __name__ == "__main__":
    main()
