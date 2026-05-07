"""A stub MCP server used for the dry-run rehearsal.

Exposes a couple of toy tools so the registry can connect, list, and call.
Replace with the organizer's hosted MCP servers once the brief unlocks.

Run standalone:
    uv run python examples/mcp_stub_server.py
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("stub")


@mcp.tool()
def lookup_business_info(key: str) -> dict:
    """Look up basic business info by key (e.g. 'hours', 'phone', 'address').

    Returns a dict with `status` and either `data` or `reason`.
    """
    facts = {
        "hours": "Mon-Fri 9:00-18:00, Sat 10:00-14:00, closed Sun",
        "phone": "+1-555-123-4567",
        "address": "123 Steppe St, Astana",
    }
    if key in facts:
        return {"status": "ok", "data": facts[key]}
    return {"status": "not_found", "reason": f"no info for key={key!r}"}


@mcp.tool()
def list_services() -> dict:
    """List the services this business offers."""
    return {
        "status": "ok",
        "data": [
            {"id": "srv_1", "name": "Haircut", "duration_min": 30, "price": 25},
            {"id": "srv_2", "name": "Color", "duration_min": 90, "price": 80},
        ],
    }


if __name__ == "__main__":
    mcp.run()
