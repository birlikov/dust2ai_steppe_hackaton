"""Read-only diagnostics over the simulator state.

Single-file evaluator helper that pulls the four ``world_*`` and
``gb_list_simulated_actions`` read tools the rest of the codebase
doesn't routinely call, so a judge can introspect simulator state
without grepping the inventory file.

Usage::

    uv run python scripts/world_inspect.py
    uv run python scripts/world_inspect.py --inject  # demo a world_inject_event call

The non-`--inject` path is purely read-only and safe to run repeatedly.
The ``--inject`` path adds one synthetic ``whatsapp`` event to the
timeline (useful for verifying the always-on WorldPoller picks it up
and routes it through the customer-facing orchestrator).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from src.core.logging import get_logger  # noqa: E402
from src.mcp.http_client import (  # noqa: E402
    McpError,
    McpTransportError,
    build_default_client,
    call_with_retry,
)

log = get_logger(__name__)


async def _safe(client, tool: str, args: dict | None = None) -> object:
    try:
        return await call_with_retry(client, tool, args or {})
    except (McpTransportError, McpError) as exc:
        return {"error": str(exc), "tool": tool}


async def amain(args: argparse.Namespace) -> int:
    async with build_default_client() as mcp:
        if args.inject:
            print("\n=== world_inject_event ===")
            payload = {
                "channel": "whatsapp",
                "payload": {
                    "from": "+12815550199",
                    "text": (
                        'world_inspect.py demo — quick check on cake "Honey" availability'
                    ),
                },
            }
            result = await _safe(mcp, "world_inject_event", payload)
            print(json.dumps(result, indent=2, default=str)[:1500])

        print("\n=== world_get_scenarios ===")
        scenarios = await _safe(mcp, "world_get_scenarios")
        print(json.dumps(scenarios, indent=2, default=str)[:1500])

        print("\n=== world_get_scenario_summary ===")
        summary = await _safe(mcp, "world_get_scenario_summary")
        print(json.dumps(summary, indent=2, default=str)[:1500])

        print("\n=== world_get_timeline ===")
        timeline = await _safe(mcp, "world_get_timeline")
        print(json.dumps(timeline, indent=2, default=str)[:2500])

        print("\n=== gb_list_simulated_actions ===")
        gb_actions = await _safe(mcp, "gb_list_simulated_actions")
        print(json.dumps(gb_actions, indent=2, default=str)[:1500])

        print("\n=== evaluator_get_evidence_summary ===")
        evidence = await _safe(mcp, "evaluator_get_evidence_summary")
        print(json.dumps(evidence, indent=2, default=str)[:1500])

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--inject",
        action="store_true",
        help="also call world_inject_event with a sample WhatsApp inbound",
    )
    args = parser.parse_args()
    sys.exit(asyncio.run(amain(args)))


if __name__ == "__main__":
    main()
