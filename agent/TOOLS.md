# TOOLS — MCP tool catalog with when-to-use guidance

The runtime has access to one MCP server, **`happycake`**, with 55 tools across 8
families. Always prefer a tool call over your memory; never invent a price, flavour,
weight, lead time, ingredient, allergen, hour, address, availability, policy, campaign
status, or order detail. Full schemas and sample shapes are in `docs/mcp_inventory.md` —
this file gives you the *when-to-use* and *gotchas* in operational form.

## How to use any tool

1. **One tool per turn until you have what you need.** Don't fan out speculatively;
   judges and the evaluator read the audit log.
2. **Pass an `idempotency_key` for any write** if the schema accepts one — the bridge
   derives one from session + message hash; reuse it on retry.
3. **On error, retry once with backoff.** If it fails again, escalate to the owner.
4. **Cite the tool result in natural language**, never raw JSON. *"Today's bake includes
   the honey, the napoleon, and the milk maiden"* — sourced from `square_list_catalog`.
5. **The server tracks every call.** A clean, purposeful sequence of tool calls is
   itself evidence that scores you points.

## Family: `square_*` — Catalog, inventory, orders (Square POS sandbox)

Use this family for product lookup, stock checks, order placement, and reading recent
order history.

| Tool | When to use | Notes |
|---|---|---|
| `square_list_catalog` | The customer asks "what do you have?", "what's available?", any open-ended menu question. **Always your first call** when discussing products. | Returns 5 seeded items. Each item has `variationId` (use for orders), `kitchenProductId` (use for kitchen tickets), `priceCents`, `category`. |
| `square_get_inventory` | The customer names a specific item and you need to confirm stock. | Pass `variationIds: [...]`. Unknown IDs return empty `counts: []` — that means "not in our catalog", not an error. |
| `square_recent_orders` | The owner asks "what's been ordered today?", or you need attribution context (e.g. "did this customer already order today?"). | Read-only. Empty until the team places orders. |
| `square_get_pos_summary` | The owner asks for a sales/dashboard overview. | Aggregates orders, revenue, channel mix. Read at workflow boot for the owner dashboard. |
| `square_recent_sales_csv` | Marketing planning — historic baseline for the $500 budget reasoning. | **Returns raw CSV string**, not JSON. Don't `json.loads()` — parse as CSV. Roughly $18k/month, ~700 orders, ~$25 ticket. |
| `square_create_order` | After the customer confirms what + how-many + channel. **Always followed by `kitchen_create_ticket`.** | Required: `items[{variationId, quantity}]`. Optional: `source` (one of `website | whatsapp | instagram | walk-in | agent`), `customerName`, `customerNote`. Returns an `orderId` you must pass to the kitchen. |
| `square_update_order_status` | When the kitchen finishes / cancels / approves an order, mirror the status to POS. | Required: `orderId`, `status`. Use sparingly — mostly the kitchen does this implicitly. |

### Gotchas

- The catalog uses `variationId` (e.g. `sq_var_honey_cake_slice`); the kitchen uses
  `productId` (e.g. `honey-cake-slice`). Map via `kitchenProductId` in the catalog
  response.
- `custom-birthday-cake` has 24h lead time and `requiresCustomWork: true` — same-day
  custom requests are not feasible; either offer a future slot or escalate to owner.

## Family: `kitchen_*` — Capacity, menu constraints, production tickets

Use this family **before any timing/availability promise** and **after every
`square_create_order`**.

| Tool | When to use | Notes |
|---|---|---|
| `kitchen_get_capacity` | **MANDATORY before any "ready by", "today by 5 PM", "available now" answer.** Returns `dailyCapacityMinutes`, `remainingCapacityMinutes`, queue load. | Hard cap: 420 min/day. Default lead time 45 min. If `remainingCapacityMinutes` is too low, offer a later slot or escalate. |
| `kitchen_get_menu_constraints` | When the customer asks how long something takes, whether it's available same-day, or whether it's halal/dietary-tagged. | Returns `prepMinutes`, `leadTimeMinutes`, `capacityUnitsPerDay`, `requiresCustomWork`. Cite naturally. |
| `kitchen_get_production_summary` | Owner dashboard / evaluator-style summary. | Aggregate ticket counts and capacity utilisation. Has `overCapacity: true` flag. |
| `kitchen_list_tickets` | Owner asks "what's in the kitchen right now?" Filter with `status` (`pending`, `accepted`, `ready`, `rejected`). | Read-only. |
| `kitchen_create_ticket` | After every `square_create_order`. **Use `productId` (e.g. `honey-cake-slice`), not `variationId`**. | Required: `orderId`, `customerName`, `items[{productId, quantity}]`. Optional: `requestedPickupAt` (ISO 8601), `notes`. |
| `kitchen_accept_ticket` | When capacity allows, mark the ticket accepted. | Required: `ticketId`. Returns `isError: true` with `"Error: Ticket not found"` if the ID is wrong. |
| `kitchen_reject_ticket` | When capacity, lead time, or inventory makes it infeasible. | Required: `ticketId`. Optional: `reason`. The evaluator wants to see both accept and reject paths used. |
| `kitchen_mark_ready` | Final step — ticket is ready for pickup/delivery. | Required: `ticketId`. The evaluator scores completion rate. |

### Gotchas

- The map between `square_*` and `kitchen_*` is asymmetric: `square_list_catalog`
  exposes `kitchenProductId` for each item — use that to construct kitchen tickets.

## Family: `marketing_*` — Budget, history, campaigns, leads

Use for the **$500 → $5,000 marketing challenge** (`marketing_get_budget` → plan →
`marketing_create_campaign` → `marketing_launch_simulated_campaign` →
`marketing_generate_leads` → `marketing_route_lead` → `marketing_report_to_owner`).

| Tool | When to use | Notes |
|---|---|---|
| `marketing_get_budget` | At the start of any marketing plan. | Returns `monthlyBudgetUsd: 500`, `targetEffectUsd: 5000`. |
| `marketing_get_sales_history` | When sizing a campaign against historical revenue. | 6 months of monthly aggregates. JSON form of `square_recent_sales_csv`. |
| `marketing_get_margin_by_product` | When choosing which products to push (highest margin = best $/click). | Honey + pistachio slices have ~64-68% margins — the strongest economics. |
| `marketing_get_campaign_metrics` | After a campaign is launched, to read its performance. | Empty array for unknown campaign IDs (silent, not an error). |
| `marketing_create_campaign` | After planning. | Required: `name`, `channel` (`instagram | google_local | whatsapp | website | mixed`), `objective`, `budgetUsd`, `targetAudience`, `offer`. Optional: `landingPath`. Returns a `campaignId`. |
| `marketing_launch_simulated_campaign` | Right after `create_campaign` to generate metrics. | Required: `campaignId`. |
| `marketing_generate_leads` | After launch, to materialise leads for routing. | Required: `campaignId`. Returns `leadId` values. |
| `marketing_route_lead` | For every lead, decide where to route it. | Required: `leadId`, `routeTo` (`website | whatsapp | instagram | owner_approval`), `reason`. Evaluator checks every lead is routed *with a reason*. |
| `marketing_adjust_campaign` | After reading metrics, propose a change. | Required: `campaignId`, `adjustment`. Optional: `expectedImpact`. Evidence of a closed-loop marketing agent. |
| `marketing_report_to_owner` | At the end of a campaign cycle. | Sends the owner a summary. The evaluator counts `owner report(s) recorded`. |

### Gotchas

- The whole loop has to be exercised end-to-end for full credit on the $500
  challenge. Skipping `route_lead` or `report_to_owner` is a visible gap.

## Family: `whatsapp_*` — WhatsApp send, receive, webhook

Use for direct customer messages on WhatsApp. **Replies to inbound DMs do not need
owner approval** (per brand book §7); just follow the brand voice.

| Tool | When to use | Notes |
|---|---|---|
| `whatsapp_list_threads` | Owner asks "what's on WhatsApp today?". | Read-only. Sandbox returns `simulated: true`. |
| `whatsapp_send` | Replying to a customer or sending a confirmation. | Required: `to` (E.164 phone, e.g. `+12815551001`), `message`. **English only.** Empty message → `isError: true`. |
| `whatsapp_register_webhook` | At bot startup once the public ngrok URL is known. | Required: `url` (HTTPS). Without this, no inbound events. |
| `whatsapp_inject_inbound` | Test/evaluator helper to simulate a customer message. | Required: `from`, `message`. For dry-run testing only. |

## Family: `instagram_*` — DMs, comments, scheduled posts (with approval gate)

Use for IG DMs and comments. **Posts go through the approval queue** (`schedule` →
owner approves via Telegram → `publish`).

| Tool | When to use | Notes |
|---|---|---|
| `instagram_list_dm_threads` | Owner overview / catching up on DMs. | Mirror of `whatsapp_list_threads`. |
| `instagram_send_dm` | Replying to a DM. | Required: `threadId`, `message`. Quirk: server accepts ANY threadId without erroring — be sure you got it from a real inbound event. |
| `instagram_reply_to_comment` | Replying to a comment under one of our posts. | Required: `commentId`, `message`. Always reply in-channel; don't redirect to DM. |
| `instagram_schedule_post` | Drafting a feed post or carousel. **Always step 1.** | Required: `imageUrl`, `caption`. Optional: `scheduledFor` (ISO 8601). Returns `scheduledPostId`. After this, send the draft to the owner via Telegram for approval. |
| `instagram_approve_post` | Called by the **Telegram bot owner-side** when the owner taps Approve. | Required: `scheduledPostId`. The agent loop does NOT call this directly. |
| `instagram_publish_post` | Final step — only after `approve_post`. | Required: `scheduledPostId`. Errors if approval gate isn't passed. |
| `instagram_register_webhook` | At bot startup with the public ngrok URL. | Required: `url`. |
| `instagram_inject_dm` | Test helper. | Mirror of `whatsapp_inject_inbound` for IG threads. |

## Family: `gb_*` — Google Business reviews, posts, metrics

Use for Google Business Profile reviews and posts. The Sugar Land profile is seeded
with 4 reviews (one negative — `rev_003`).

| Tool | When to use | Notes |
|---|---|---|
| `gb_list_reviews` | Reading current reviews to draft replies. | Read-only. Stable IDs `rev_001..rev_004`. |
| `gb_get_metrics` | Owner dashboard / discovery overview. | Returns view + click counts. Default period `last_30_days`. |
| `gb_list_simulated_actions` | Audit view of all GB replies and posts the team has recorded. | Read-only. |
| `gb_simulate_reply` | Reply to a review. **Always reply in-channel, never delete.** | Required: `reviewId` (must be valid), `reply`. Tone: warm, factual, fix-on-us for the negative review. |
| `gb_simulate_post` | Owner-approved Google Business post (e.g. "Today's bake is out"). | Required: `content`. Optional: `callToAction: {label, url}`, `photoUrl`. Treat like an Instagram post — go through approval queue. |

## Family: `world_*` — Simulation engine (test/scoring infrastructure)

These tools drive the deterministic scenario engine. **They are not for
customer-visible flows** — they belong in the test/integration layer.

| Tool | When to use | Notes |
|---|---|---|
| `world_get_scenarios` | Reading scenario list at startup. | Two scenarios: `launch-day-revenue-engine` (480 min, 10× compression) and `weekend-capacity-crunch` (360 min, 8× compression). |
| `world_get_timeline` | Debugging — what events have been delivered? | Read-only. |
| `world_get_scenario_summary` | Progress check during a run. | Read-only. |
| `world_start_scenario` | Once at the start of a test/integration run. | Required: `scenarioId`. Optional: `seed`. **Resets state.** |
| `world_next_event` | The integration test loop polls this. | Mutating; returns the next deterministic event. |
| `world_advance_time` | Skip ahead in scenario time. | Required: `minutes`. Mutating. |
| `world_inject_event` | Inject a test/eval event into the timeline. | Required: `channel`, `type`, `payload`. Useful for targeted regression tests. |

## Family: `evaluator_*` — Self-grading and team report

These tools are for the integration tests and submission flow — not customer-visible.

| Tool | When to use | Notes |
|---|---|---|
| `evaluator_get_evidence_summary` | Periodic checkpoint during the build to confirm activity is being tracked. | Returns counts including `auditCalls` (every MCP call). |
| `evaluator_score_marketing_loop` | Confirm the $500 loop is closed. | The `gaps` array tells you exactly what's missing. |
| `evaluator_score_pos_kitchen_flow` | Confirm POS + kitchen are end-to-end. | Four pipeline steps; all four needed for max. |
| `evaluator_score_channel_response` | Confirm WA + IG + GB all see traffic. | Three channels scored separately. |
| `evaluator_score_world_scenario` | Confirm scenario runs are recorded. | Baseline 40/100 just for making any MCP calls. |
| `evaluator_generate_team_report` | Final submission step. | Optional: `repoUrl`, `websiteUrl`, `notes`. Pass real URLs at submission. |

## Cross-cutting

- **Auth** — single `X-Team-Token` header, configured in `.claude/settings.local.json`.
  All state is namespaced per token. Never leak the token in any reply.
- **Latency** — typical 220-330 ms; budget ~300 ms per call when planning a multi-tool
  turn.
- **No rate limits observed** — but be deliberate; spam in the audit log reads as
  unprofessional.
- **English-only** for any customer-visible message you send via these tools.
