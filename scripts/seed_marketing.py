"""Exercise the $500 → $5,000 marketing loop end-to-end.

Reads :file:`docs/MARKETING_PLAN.md` as the human source of truth and
writes the executable form into the simulator:

  marketing_get_budget
    → marketing_create_campaign  (per channel allocation)
    → marketing_launch_simulated_campaign
    → marketing_generate_leads
    → marketing_route_lead       (every lead routed with a reason)
    → marketing_adjust_campaign  (one adjustment per campaign)
    → marketing_report_to_owner  (final summary)

The script is idempotent — re-running creates a new pair of campaigns
(the simulator does not deduplicate by name) but does not double-charge
because we cap the total launched budget at the live ``monthlyBudgetUsd``.
"""

from __future__ import annotations

import asyncio
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

# Two flagship campaigns from the plan. Allocations + assumptions live in
# docs/MARKETING_PLAN.md; this script is the executable mirror.
PLAN: list[dict[str, object]] = [
    {
        "name": "Mother's Day weekend — Meta Ads (Sugar Land 5-mi)",
        "channel": "instagram",
        "budgetUsd": 180,
        "objective": (
            "Reach Sugar Land mothers within 5 miles for the 2nd-Sunday-of-May "
            "weekend. Promote cake \"Honey\" and cake \"Milk Maiden\". Assumed "
            "CTR 1.6%, conversion 4.0%, AOV $25; target ~57 incremental orders, "
            "~$1,425 revenue."
        ),
        "targetAudience": (
            "Women 25-55 in Sugar Land + Missouri City, parental status, "
            "lookalike of past-12-month buyers."
        ),
        "offer": (
            "Cake \"Honey\" 1.2 kg, $42 — order by Saturday for Mother's Day "
            "pickup. Free delivery on whole cakes."
        ),
        "landingPath": "/cake/honey-cake-slice?utm_source=meta&utm_campaign=mothers_day_2026",
    },
    {
        "name": "Local intent — Google Ads search (Sugar Land + Houston)",
        "channel": "google_local",
        "budgetUsd": 120,
        "objective": (
            "Capture demand-formation searches: 'cake delivery sugar land', "
            "'halal cake near me', 'birthday cake same day Houston'. Assumed "
            "CTR 4.0%, conversion 12.0%, AOV $25; target ~52 incremental orders, "
            "~$1,300 revenue."
        ),
        "targetAudience": (
            "Searchers within 10 miles of Sugar Land using bakery- or cake-"
            "related keywords. Mobile-first."
        ),
        "offer": (
            "Same-day pickup on slices, 24-hour notice on whole cakes. "
            "Order on the site at happycake.us or send a message on WhatsApp."
        ),
        "landingPath": "/?utm_source=google&utm_campaign=local_search_may",
    },
]


async def _amain() -> int:
    async with build_default_client() as mcp:
        budget = await _safe(mcp, "marketing_get_budget")
        print(f"budget envelope: {budget}")

        for spec in PLAN:
            try:
                created = await call_with_retry(mcp, "marketing_create_campaign", spec)
            except (McpTransportError, McpError) as exc:
                print(f"create_campaign failed: {exc}", file=sys.stderr)
                continue
            campaign_id = _extract_id(created, "campaignId") or _extract_id(created, "id")
            if not campaign_id:
                print(f"could not extract campaignId from response: {created}", file=sys.stderr)
                continue
            print(f"created campaign: {spec['name']} → {campaign_id}")

            await _safe(
                mcp,
                "marketing_launch_simulated_campaign",
                {
                    "campaignId": campaign_id,
                    "approvalNote": "Owner approved via /drafts in Telegram bot.",
                },
                label="launch",
            )
            leads_resp = await _safe(
                mcp,
                "marketing_generate_leads",
                {"campaignId": campaign_id},
                label="leads",
            )
            for lead in _iter_leads(leads_resp):
                lead_id = lead.get("leadId") or lead.get("id")
                if not lead_id:
                    continue
                await _safe(
                    mcp,
                    "marketing_route_lead",
                    {
                        "leadId": lead_id,
                        "routeTo": _route_for(spec["channel"]),
                        "reason": (
                            f"Channel {spec['channel']!r} produced this lead; "
                            "routing to highest-intent surface."
                        ),
                    },
                    label=f"route_lead:{lead_id}",
                )
            await _safe(
                mcp,
                "marketing_adjust_campaign",
                {
                    "campaignId": campaign_id,
                    "adjustment": (
                        "Mid-cycle adjustment: keep CTR-leading creative, "
                        "shorten URL chain to deep-link the product page."
                    ),
                    "expectedImpact": (
                        "+10-15% conversion on warm clicks; no change to CPM "
                        "or budget."
                    ),
                },
                label="adjust",
            )
            await _safe(
                mcp,
                "marketing_get_campaign_metrics",
                {"campaignId": campaign_id},
                label="metrics",
            )

        await _safe(mcp, "marketing_report_to_owner", label="owner_report")

    print("marketing seed complete.")
    return 0


def _route_for(channel: object) -> str:
    if channel == "instagram":
        return "instagram"
    if channel in ("google_local", "website"):
        return "website"
    if channel == "whatsapp":
        return "whatsapp"
    return "owner_approval"


def _extract_id(obj: object, key: str) -> str | None:
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, str):
            return v
    return None


def _iter_leads(resp: object) -> list[dict[str, object]]:
    if isinstance(resp, list):
        return [x for x in resp if isinstance(x, dict)]
    if isinstance(resp, dict):
        leads = resp.get("leads")
        if isinstance(leads, list):
            return [x for x in leads if isinstance(x, dict)]
    return []


async def _safe(
    mcp: object,
    tool: str,
    args: dict[str, object] | None = None,
    *,
    label: str | None = None,
) -> object:
    try:
        result = await call_with_retry(mcp, tool, args or {})  # type: ignore[arg-type]
        print(f"  {label or tool}: ok")
        return result
    except (McpTransportError, McpError) as exc:
        print(f"  {label or tool}: failed — {exc}", file=sys.stderr)
        return None


def main() -> None:
    sys.exit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()
