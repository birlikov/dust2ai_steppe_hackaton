# MCP Inventory (as of 2026-05-09T10:00:00Z)

## Server: happycake

- **URL**: `https://www.steppebusinessclub.com/api/mcp`
- **Auth**: `X-Team-Token` header (value in `SBC_TEAM_TOKEN` env var or `.claude/settings.local.json`)
- **Status**: reachable
- **Protocol**: JSON-RPC 2.0 over HTTPS POST (`method: tools/call`, `method: tools/list`)
- **Server name reported**: `steppebusinessclub-hackathon-mcp` v1.0.0
- **Total tools**: 55
- **Resources/list**: not supported (returns `-32601 Method not found`)
- **Prompts/list**: not supported (returns `-32601 Method not found`)
- **Initialize latency**: ~300ms; subsequent calls ~220-310ms

All tools return a JSON-RPC result envelope:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [{"type": "text", "text": "<JSON string or plain text>"}],
    "isError": true   // only present on tool-level errors
  }
}
```
Text content is always a JSON-stringified object or plain string — callers must `json.loads()` the `text` field. Unknown tool names return a top-level JSON-RPC error (`code: -32004`).

---

## Family: square_*  (7 tools)

### square_list_catalog
- **Purpose**: Return the full Happy Cake POS catalog (simulated; no Square credentials needed).
- **Input schema**:
  - `limit` (number, optional) — max items to return
- **Sample call**:
  ```json
  {"limit": 5}
  ```
- **Sample response (success)**:
  ```json
  {
    "mode": "simulated",
    "catalog": [
      {"id": "sq_item_honey_cake_slice", "variationId": "sq_var_honey_cake_slice",
       "name": "Honey cake slice", "category": "slices", "priceCents": 850,
       "description": "Individual honey cake slice for walk-ins and quick pickup.",
       "kitchenProductId": "honey-cake-slice"},
      {"id": "sq_item_pistachio_roll", "variationId": "sq_var_pistachio_roll",
       "name": "Pistachio roll", "category": "slices", "priceCents": 950,
       "kitchenProductId": "pistachio-roll"},
      {"id": "sq_item_custom_birthday_cake", "variationId": "sq_var_custom_birthday_cake",
       "name": "Custom birthday cake", "category": "custom", "priceCents": 9500,
       "description": "Custom celebration cake with human approval required.",
       "kitchenProductId": "custom-birthday-cake"}
    ]
  }
  ```
- **Sample response (not found / error)**: N/A — returns empty `catalog: []` for empty results.
- **Notes**: Read-only. Catalog appears static/seeded (5 items found with `limit: 5`). `variationId` is the key needed for `square_create_order` and `square_get_inventory`. `kitchenProductId` maps to kitchen family.
- **Latency p50**: ~305ms

---

### square_get_inventory
- **Purpose**: Return stock counts for specific catalog variation IDs.
- **Input schema**:
  - `variationIds` (array of string, **required**) — list of variation IDs to query
- **Sample call**:
  ```json
  {"variationIds": ["sq_var_honey_cake_slice", "sq_var_pistachio_roll"]}
  ```
- **Sample response (success)**:
  ```json
  {"mode": "simulated", "counts": [{"variationId": "sq_var_honey_cake_slice", "quantity": 12}, ...]}
  ```
- **Sample response (not found / error)**:
  - Unknown IDs: `{"mode": "simulated", "counts": []}` (no error, empty array)
  - Missing required arg: `isError: true`, text `"Error: variationIds is required"`
- **Notes**: Read-only. Bad IDs silently return empty counts (not an error). Missing required arg triggers `isError`.
- **Latency p50**: ~250ms

---

### square_recent_orders
- **Purpose**: Fetch recent simulated POS orders for this team.
- **Input schema**:
  - `sinceISO` (string, optional) — ISO 8601 filter timestamp
  - `limit` (number, optional) — max orders
- **Sample call**:
  ```json
  {"limit": 3}
  ```
- **Sample response (success)**:
  ```json
  {"mode": "simulated", "orders": []}
  ```
  (empty at start of hackathon; populated after `square_create_order` calls)
- **Sample response (error)**: No error observed; always returns empty orders list if none exist.
- **Notes**: Read-only. State is per-team, scoped by token. Empty until orders are created.
- **Latency p50**: ~244ms

---

### square_get_pos_summary
- **Purpose**: Return aggregated POS stats — order count, revenue, channel mix, kitchen handoff readiness.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  {
    "mode": "simulated",
    "orders": 0,
    "revenueCents": 0,
    "byStatus": {},
    "bySource": {},
    "events": 0,
    "kitchenHandoffRecommended": 0
  }
  ```
- **Sample response (error)**: N/A — always returns summary shape.
- **Notes**: Read-only. Used by evaluator. `bySource` will contain keys like `whatsapp`, `instagram`, `walk-in`, `agent`.
- **Latency p50**: ~255ms

---

### square_recent_sales_csv
- **Purpose**: Return canonical seeded 6-month historical sales CSV for marketing-budget reasoning.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  "month,revenue_usd,orders,avg_ticket_usd\n2025-11,14820,612,24.22\n2025-12,19240,738,26.07\n2026-01,15110,621,24.33\n2026-02,16890,668,25.28\n2026-03,17640,691,25.53\n2026-04,18320,724,25.30"
  ```
  (Note: returns raw CSV string, not JSON — do not `json.loads()` this one)
- **Sample response (error)**: N/A — static seeded data.
- **Notes**: Read-only. The only tool that returns plain text (CSV), not JSON. ~$18k/month revenue, ~700 orders/month at ~$25 avg ticket.
- **Latency p50**: ~231ms

---

### square_create_order  *(MUTATING — not called in read-only pass)*
- **Purpose**: Create a simulated POS order from a channel (website/whatsapp/instagram/walk-in/agent). Use `kitchen_create_ticket` after this for production handoff.
- **Input schema**:
  - `items` (array, **required**): each item has `variationId` (string, required), `quantity` (number, required), `note` (string, optional)
  - `source` (string, optional): `website | whatsapp | instagram | walk-in | agent`
  - `customerName` (string, optional)
  - `customerNote` (string, optional)
- **Sample call**:
  ```json
  {
    "items": [{"variationId": "sq_var_honey_cake_slice", "quantity": 2}],
    "source": "whatsapp",
    "customerName": "Alice"
  }
  ```
- **Notes**: Side-effecting. Creates a POS record scoped to team token. Evaluator scores by order count and channel diversity. Must precede `kitchen_create_ticket`.
- **Latency p50**: untested (mutating)

---

### square_update_order_status  *(MUTATING — not called in read-only pass)*
- **Purpose**: Update a simulated order status (approved, kitchen-handoff, ready, complete, cancelled).
- **Input schema**:
  - `orderId` (string, **required**)
  - `status` (string, **required**)
  - `note` (string, optional)
- **Notes**: Side-effecting. Requires a valid `orderId` from a prior `square_create_order` call.
- **Latency p50**: untested (mutating)

---

## Family: kitchen_*  (6 tools)

### kitchen_get_capacity
- **Purpose**: Return simulated kitchen capacity, default lead time, and current queue load.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  {
    "dailyCapacityMinutes": 420,
    "defaultLeadTimeMinutes": 45,
    "activePrepMinutes": 0,
    "remainingCapacityMinutes": 420,
    "queuedTickets": 0,
    "acceptedTickets": 0
  }
  ```
- **Sample response (error)**: N/A — always returns capacity shape.
- **Notes**: Read-only. 420 min/day total (7h). Check before `kitchen_create_ticket` to avoid over-booking.
- **Latency p50**: ~252ms

---

### kitchen_get_menu_constraints
- **Purpose**: Return per-product prep time, lead time, daily capacity units, and whether custom work is required.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  [
    {"productId": "honey-cake-slice", "name": "Honey cake slice",
     "prepMinutes": 3, "leadTimeMinutes": 5, "capacityUnitsPerDay": 80, "requiresCustomWork": false},
    {"productId": "custom-birthday-cake", "name": "Custom birthday cake",
     "prepMinutes": 90, "leadTimeMinutes": 1440, "capacityUnitsPerDay": 4, "requiresCustomWork": true},
    {"productId": "office-dessert-box", "name": "Office dessert box",
     "prepMinutes": 45, "leadTimeMinutes": 180, "capacityUnitsPerDay": 8, "requiresCustomWork": true}
  ]
  ```
  Full set: 5 products. `requiresCustomWork: true` items need human approval before `kitchen_accept_ticket`.
- **Sample response (error)**: N/A — static seeded data.
- **Notes**: Read-only. Critical for routing logic — `leadTimeMinutes: 1440` (24h) for custom cakes means same-day requests must be rejected.
- **Latency p50**: ~256ms

---

### kitchen_list_tickets
- **Purpose**: List simulated kitchen tickets for this team, optionally filtered by status.
- **Input schema**:
  - `status` (string, optional) — e.g. `pending`, `accepted`, `ready`, `rejected`
- **Sample call**:
  ```json
  {"status": "pending"}
  ```
- **Sample response (success)**:
  ```json
  []
  ```
  (empty at start; array of ticket objects after creation)
- **Sample response (error)**: N/A — returns empty array if no tickets exist.
- **Notes**: Read-only. State is per-team. Ticket shape not yet observed (no tickets created in read-only pass).
- **Latency p50**: ~249ms

---

### kitchen_get_production_summary
- **Purpose**: Return aggregate ticket counts, capacity utilization, rejection counts — used by evaluator.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  {
    "tickets": 0,
    "byStatus": {},
    "events": 0,
    "dailyCapacityMinutes": 420,
    "usedPrepMinutes": 0,
    "remainingCapacityMinutes": 420,
    "overCapacity": false
  }
  ```
- **Sample response (error)**: N/A — always returns summary shape.
- **Notes**: Read-only. `overCapacity: true` signals the agent must start rejecting or rescheduling.
- **Latency p50**: ~245ms

---

### kitchen_create_ticket  *(MUTATING — not called in read-only pass)*
- **Purpose**: Create a production ticket from a POS or channel order.
- **Input schema**:
  - `orderId` (string, **required**)
  - `customerName` (string, **required**)
  - `items` (array, **required**): each has `productId` (string, required), `quantity` (number, required)
  - `requestedPickupAt` (string, optional) — ISO 8601
  - `notes` (string, optional)
- **Notes**: Side-effecting. `productId` must match `kitchen_get_menu_constraints` IDs (e.g. `honey-cake-slice`, not `sq_var_...`). Agent must call this after `square_create_order`.
- **Latency p50**: untested (mutating)

---

### kitchen_accept_ticket  *(MUTATING — tested for failure shape only)*
- **Purpose**: Accept a queued kitchen ticket if capacity and timing are feasible.
- **Input schema**:
  - `ticketId` (string, **required**)
  - `note` (string, optional)
- **Sample response (not found / error)**:
  ```json
  {"content": [{"type": "text", "text": "Error: Ticket not found"}], "isError": true}
  ```
- **Notes**: Side-effecting. Returns `isError: true` with plain text message if ticket not found.
- **Latency p50**: ~285ms

---

### kitchen_reject_ticket  *(MUTATING — not called in read-only pass)*
- **Purpose**: Reject a ticket when inventory, lead time, or capacity makes it unfeasible.
- **Input schema**:
  - `ticketId` (string, **required**)
  - `reason` (string, optional)
- **Notes**: Side-effecting. Evaluator checks both accept and reject paths.
- **Latency p50**: untested (mutating)

---

### kitchen_mark_ready  *(MUTATING — not called in read-only pass)*
- **Purpose**: Mark an accepted ticket ready for pickup.
- **Input schema**:
  - `ticketId` (string, **required**)
  - `pickupNote` (string, optional)
- **Notes**: Side-effecting. Final step of kitchen flow; evaluator scores completion rate.
- **Latency p50**: untested (mutating)

---

## Family: marketing_*  (9 tools)

### marketing_get_budget
- **Purpose**: Return the monthly marketing budget constraint and target ($500 -> $5,000 ROI challenge).
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  {"monthlyBudgetUsd": 500, "targetEffectUsd": 5000, "challenge": "$500 -> $5,000"}
  ```
- **Sample response (error)**: N/A — always returns budget shape.
- **Notes**: Read-only. Static. Read at workflow boot to anchor campaign planning.
- **Latency p50**: ~232ms

---

### marketing_get_sales_history
- **Purpose**: Return 6 months of anonymized sales data for campaign planning.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  [
    {"month": "2025-11", "revenueUsd": 14820, "orders": 612, "avgTicketUsd": 24.22},
    {"month": "2025-12", "revenueUsd": 19240, "orders": 738, "avgTicketUsd": 26.07},
    {"month": "2026-04", "revenueUsd": 18320, "orders": 724, "avgTicketUsd": 25.30}
  ]
  ```
  (6 rows total, Nov 2025 through Apr 2026)
- **Notes**: Read-only. Same data as `square_recent_sales_csv` but in JSON array format. Prefer this for programmatic use.
- **Latency p50**: ~251ms

---

### marketing_get_margin_by_product
- **Purpose**: Return product price and estimated gross margin percentage for budget allocation.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  [
    {"productId": "honey-cake-slice", "name": "Honey cake slice", "priceUsd": 8.50, "estimatedMarginPct": 68},
    {"productId": "whole-honey-cake", "name": "Whole honey cake", "priceUsd": 55, "estimatedMarginPct": 62},
    {"productId": "custom-birthday-cake", "name": "Custom birthday cake", "priceUsd": 95, "estimatedMarginPct": 58},
    {"productId": "office-dessert-box", "name": "Office dessert box", "priceUsd": 120, "estimatedMarginPct": 60}
  ]
  ```
  (5 products total)
- **Notes**: Read-only. Static seeded data. Slices (honey, pistachio) have highest margins (64-68%).
- **Latency p50**: ~230ms

---

### marketing_get_campaign_metrics
- **Purpose**: Read simulated campaign metrics for this team.
- **Input schema**:
  - `campaignId` (string, optional) — filter to one campaign; omit for all
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  []
  ```
  (empty array if no campaigns exist; array of metric objects after campaigns are created and launched)
- **Sample response (not found / error)**: Unknown `campaignId` silently returns `[]` (not an error).
- **Notes**: Read-only. No error on bad campaign ID — returns empty array. Only meaningful after `marketing_create_campaign` + `marketing_launch_simulated_campaign`.
- **Latency p50**: ~231ms

---

### marketing_create_campaign  *(MUTATING — not called in read-only pass)*
- **Purpose**: Create a simulated campaign plan and record it in team state.
- **Input schema**:
  - `name` (string, **required**)
  - `channel` (string, **required**): `instagram | google_local | whatsapp | website | mixed`
  - `objective` (string, **required**)
  - `budgetUsd` (number, **required**)
  - `targetAudience` (string, **required**)
  - `offer` (string, **required**)
  - `landingPath` (string, optional)
- **Notes**: Side-effecting. Returns a `campaignId` needed for subsequent calls. Must be followed by `marketing_launch_simulated_campaign` to generate metrics.
- **Latency p50**: untested (mutating)

---

### marketing_launch_simulated_campaign  *(MUTATING — not called in read-only pass)*
- **Purpose**: Launch a created campaign, generate impressions/clicks/leads/orders estimates.
- **Input schema**:
  - `campaignId` (string, **required**)
  - `approvalNote` (string, optional)
- **Notes**: Side-effecting. Must be called after `marketing_create_campaign`. Generates leads that `marketing_generate_leads` then surfaces.
- **Latency p50**: untested (mutating)

---

### marketing_generate_leads  *(MUTATING — not called in read-only pass)*
- **Purpose**: Generate simulated leads from campaign metrics for routing.
- **Input schema**:
  - `campaignId` (string, **required**)
- **Notes**: Side-effecting. Produces `leadId` values for use with `marketing_route_lead`.
- **Latency p50**: untested (mutating)

---

### marketing_route_lead  *(MUTATING — not called in read-only pass)*
- **Purpose**: Record how an agent routed a marketing lead to a sales channel.
- **Input schema**:
  - `leadId` (string, **required**)
  - `routeTo` (string, **required**): `website | whatsapp | instagram | owner_approval`
  - `reason` (string, **required**)
- **Notes**: Side-effecting. Evaluator checks routing decisions exist and are justified.
- **Latency p50**: untested (mutating)

---

### marketing_adjust_campaign  *(MUTATING — not called in read-only pass)*
- **Purpose**: Record an agent-driven adjustment after reading campaign metrics.
- **Input schema**:
  - `campaignId` (string, **required**)
  - `adjustment` (string, **required**)
  - `expectedImpact` (string, optional)
- **Notes**: Side-effecting. Evaluator checks for this as evidence of a closed-loop marketing agent.
- **Latency p50**: untested (mutating)

---

### marketing_report_to_owner  *(MUTATING — not called in read-only pass)*
- **Purpose**: Summarize campaign plan, simulated results, lead routing, and next actions for the owner.
- **Input schema**: none
- **Notes**: Side-effecting (records a report event). Evaluator checks `owner report(s) recorded` count. Listed as mutating in task brief.
- **Latency p50**: untested (mutating)

---

## Family: world_*  (6 tools)

### world_get_scenarios
- **Purpose**: List available deterministic time-compressed business scenarios.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  [
    {
      "id": "launch-day-revenue-engine",
      "name": "Launch day revenue engine",
      "description": "A deterministic, time-compressed day of inbound demand, marketing pressure, POS orders, and kitchen constraints.",
      "seed": 9100510,
      "durationMinutes": 480,
      "timeCompression": "1 simulator hour = 10 real minutes"
    },
    {
      "id": "weekend-capacity-crunch",
      "name": "Weekend capacity crunch",
      "description": "A compressed Saturday with strong demand, custom cake constraints, complaints, and capacity tradeoffs.",
      "seed": 9100520,
      "durationMinutes": 360,
      "timeCompression": "1 simulator hour = 8 real minutes"
    }
  ]
  ```
- **Notes**: Read-only. Two scenarios available. `launch-day-revenue-engine` is the primary evaluator scenario (480 min, 10x compression). Seed is deterministic — same events every run.
- **Latency p50**: ~222ms

---

### world_get_timeline
- **Purpose**: Read the per-team world timeline for debugging and evaluator scoring.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success — no active scenario)**:
  ```json
  {"run": null, "timeline": []}
  ```
- **Notes**: Read-only. Returns event log once a scenario is started. Use for debugging event delivery.
- **Latency p50**: ~227ms

---

### world_get_scenario_summary
- **Purpose**: Return scenario progress: delivered events, channel mix, current minute, remaining events.
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success — not started)**:
  ```json
  {"status": "not_started", "timelineEvents": 0}
  ```
- **Notes**: Read-only. Check before/after `world_next_event` calls to gauge progress.
- **Latency p50**: ~241ms

---

### world_start_scenario  *(MUTATING — not called in read-only pass)*
- **Purpose**: Start a scenario and reset the team's world timeline.
- **Input schema**:
  - `scenarioId` (string, **required**) — from `world_get_scenarios`
  - `seed` (number, optional) — override default seed for reproducibility
- **Notes**: Side-effecting. Resets state. Call once at hackathon start. Use `scenarioId: "launch-day-revenue-engine"`.
- **Latency p50**: untested (mutating)

---

### world_next_event  *(MUTATING — not called in read-only pass)*
- **Purpose**: Deliver the next deterministic event in the active scenario timeline.
- **Input schema**: none
- **Notes**: Side-effecting. Core of the scenario loop — call repeatedly to drive events. Each event is a channel inbound (WhatsApp, Instagram, POS, etc.).
- **Latency p50**: untested (mutating)

---

### world_advance_time  *(MUTATING — not called in read-only pass)*
- **Purpose**: Advance the active scenario clock by N simulator minutes and return due events preview.
- **Input schema**:
  - `minutes` (number, **required**)
- **Notes**: Side-effecting. Alternative to `world_next_event` for time-skipping. Task brief lists as prohibited in read-only pass.
- **Latency p50**: untested (mutating)

---

### world_inject_event  *(MUTATING — not called in read-only pass)*
- **Purpose**: Inject a custom evaluator or test event into the team timeline without touching real channels.
- **Input schema**:
  - `channel` (string, **required**)
  - `type` (string, **required**)
  - `payload` (object, **required**)
  - `priority` (string, optional)
- **Notes**: Side-effecting. Useful for testing agent responses to specific event types without running the full scenario.
- **Latency p50**: untested (mutating)

---

## Family: evaluator_*  (5 tools)

### evaluator_get_evidence_summary
- **Purpose**: Collect per-team simulation evidence across all domains (world, marketing, POS, kitchen, channels, MCP audit log).
- **Input schema**: none
- **Sample call**:
  ```json
  {}
  ```
- **Sample response (success)**:
  ```json
  {
    "policy": "No real credentials. Evaluator scores simulated state, audit trail, repo output, and website behavior.",
    "websiteArtifact": "happycake.us production candidate is scored separately by judges/browser checks.",
    "counts": {
      "worldEvents": 0, "marketingCampaigns": 0, "marketingLeads": 0,
      "squareOrders": 0, "kitchenTickets": 0,
      "whatsappInbound": 0, "whatsappOutbound": 0,
      "instagramActions": 0, "gbusinessReviews": 0, "gbusinessReplies": 0,
      "auditCalls": 19
    }
  }
  ```
- **Notes**: Read-only. `auditCalls` increments with every MCP tool call — the server tracks all activity. Use this to check scoring progress.
- **Latency p50**: ~308ms

---

### evaluator_score_marketing_loop
- **Purpose**: Score the $500 -> $5,000 marketing loop from simulator evidence.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "dimension": "marketing loop", "score": 0, "maxScore": 100,
    "evidence": ["0 campaign(s) created", "0 simulated lead(s) generated/routed", "0 owner report(s) recorded", "0 POS-style order(s) available for attribution"],
    "gaps": ["No campaign created", "No simulated leads generated", "No owner-facing marketing report", "No POS order evidence tied to demand"]
  }
  ```
- **Notes**: Read-only. Use periodically to check progress. `gaps` array tells you exactly what actions are missing.
- **Latency p50**: ~302ms

---

### evaluator_score_pos_kitchen_flow
- **Purpose**: Score Square/POS order flow and kitchen handoff evidence.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "dimension": "POS + kitchen handoff", "score": 0, "maxScore": 100,
    "evidence": ["0 Square/POS simulator order(s)", "0 kitchen ticket(s)", "0 accepted, 0 ready, 0 rejected/escalated"],
    "gaps": ["No POS-style order created", "No kitchen ticket handoff", "No capacity-aware accept/reject decision", "No ready-for-pickup completion evidence"]
  }
  ```
- **Notes**: Read-only. Scores 4 distinct pipeline steps — all four needed for max score.
- **Latency p50**: ~318ms

---

### evaluator_score_channel_response
- **Purpose**: Score WhatsApp, Instagram, and Google Business response evidence.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "dimension": "channel response", "score": 0, "maxScore": 100,
    "evidence": ["0 WhatsApp inbound event(s)", "0 WhatsApp response(s)", "0 Instagram action(s)", "0 Google review(s), 0 proposed reply/replies"],
    "gaps": ["No channel events processed", "No WhatsApp response evidence", "No Instagram handling evidence", "No Google Business review reply evidence"]
  }
  ```
- **Notes**: Read-only. Three distinct channels — WhatsApp, Instagram, Google Business — each scored separately.
- **Latency p50**: ~302ms

---

### evaluator_score_world_scenario
- **Purpose**: Score deterministic world/scenario execution and MCP audit behavior.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "dimension": "world scenario execution", "score": 40, "maxScore": 100,
    "evidence": ["No active scenario run", "0 event(s) in timeline", "23 recent MCP call(s) in mcp_audit_log"],
    "gaps": ["No world_start_scenario evidence", "No world_next_event/world_advance_time delivery evidence"]
  }
  ```
  Note: score of 40 was observed just from having MCP audit calls — the server rewards active engagement.
- **Notes**: Read-only. Score starts at 40 baseline if team has made MCP calls. Increases with scenario events delivered.
- **Latency p50**: ~301ms

---

### evaluator_generate_team_report
- **Purpose**: Generate a combined evidence report across all dimensions for judges/leaderboard.
- **Input schema**:
  - `repoUrl` (string, optional)
  - `websiteUrl` (string, optional)
  - `notes` (string, optional)
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "policy": "No real credentials. ...",
    "repoUrl": "repo URL not provided",
    "score": 10,
    "maxScore": 100,
    "dimensions": [
      {"dimension": "marketing loop", "score": 0, "maxScore": 100, ...},
      {"dimension": "POS + kitchen handoff", "score": 0, "maxScore": 100, ...},
      {"dimension": "channel response", "score": 0, "maxScore": 100, ...},
      {"dimension": "world scenario execution", "score": 40, "maxScore": 100, ...}
    ]
  }
  ```
- **Sample response (error)**: Type mismatch (`repoUrl: 12345`) is silently accepted — no error, treats as-is.
- **Notes**: Read-only for scoring purposes. No type validation on optional fields. Call with `repoUrl` and `websiteUrl` when submitting to judges.
- **Latency p50**: ~325ms (slowest observed)

---

## Family: whatsapp_*  (4 tools)

### whatsapp_list_threads
- **Purpose**: List recent WhatsApp conversations the team has handled.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {"inbound": [], "outbound": [], "simulated": true}
  ```
- **Notes**: Read-only. All channels are sandboxed (`simulated: true`). Empty until `whatsapp_inject_inbound` or real webhook events arrive.
- **Latency p50**: ~218ms

---

### whatsapp_send  *(MUTATING — tested for failure shape only)*
- **Purpose**: Send a text message to a customer on WhatsApp (sandboxed).
- **Input schema**:
  - `to` (string, **required**): E.164 phone number e.g. `+12815551001`
  - `message` (string, **required**): message body (English only)
- **Sample response (not found / error)**:
  ```json
  {"content": [{"type": "text", "text": "Error: to and message are required"}], "isError": true}
  ```
  (triggered by empty string for `message`)
- **Notes**: Side-effecting. Customer must be in team's whitelisted simulated customers list. Evaluator tracks `whatsappOutbound` count.
- **Latency p50**: ~228ms

---

### whatsapp_register_webhook  *(MUTATING — not called in read-only pass)*
- **Purpose**: Register a public URL to receive inbound WhatsApp events forwarded by the MCP server.
- **Input schema**:
  - `url` (string, **required**): public HTTPS URL (ngrok or Cloudflare Tunnel)
- **Notes**: Side-effecting. Call once at startup with the ngrok tunnel URL. Required for the agent to receive inbound messages.
- **Latency p50**: untested (mutating)

---

### whatsapp_inject_inbound  *(MUTATING — not called in read-only pass)*
- **Purpose**: Inject a simulated inbound WhatsApp message from a fake customer (test/evaluator use).
- **Input schema**:
  - `from` (string, **required**): E.164 phone number of simulated customer
  - `message` (string, **required**)
- **Notes**: Side-effecting. Does not actually message anyone. Used for dry-run testing of agent responses.
- **Latency p50**: untested (mutating)

---

## Family: instagram_*  (6 tools)

### instagram_list_dm_threads
- **Purpose**: List the team's recent Instagram DM conversations.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {"inbound": [], "outbound": [], "simulated": true}
  ```
- **Notes**: Read-only. Mirrors WhatsApp structure.
- **Latency p50**: ~256ms

---

### instagram_send_dm  *(MUTATING — tested for failure shape only)*
- **Purpose**: Send a DM to an Instagram user thread.
- **Input schema**:
  - `threadId` (string, **required**)
  - `message` (string, **required**)
- **Sample response (bad threadId)**: Returns success `"[simulated] DM recorded for thread NONEXISTENT_THREAD."` — the server does NOT validate threadId existence. All sends succeed silently.
- **Notes**: Side-effecting. Quirk: no error on unknown threadId — simulator accepts any thread ID.
- **Latency p50**: ~308ms

---

### instagram_reply_to_comment  *(MUTATING — not called in read-only pass)*
- **Purpose**: Reply to a comment under an Instagram post.
- **Input schema**:
  - `commentId` (string, **required**)
  - `message` (string, **required**)
- **Notes**: Side-effecting. Evaluator tracks `instagramActions` count.
- **Latency p50**: untested (mutating)

---

### instagram_schedule_post  *(MUTATING — not called in read-only pass)*
- **Purpose**: Queue a post for owner approval. Returns `scheduledPostId`. NOT published until `instagram_publish_post` is called after owner approval.
- **Input schema**:
  - `imageUrl` (string, **required**)
  - `caption` (string, **required**)
  - `scheduledFor` (string, optional): ISO 8601 timestamp
- **Notes**: Side-effecting. Two-step publish flow: schedule -> approve (via Telegram bot) -> publish.
- **Latency p50**: untested (mutating)

---

### instagram_approve_post  *(MUTATING — not called in read-only pass)*
- **Purpose**: Owner-side approval called by Telegram bot when owner taps "Approve".
- **Input schema**:
  - `scheduledPostId` (string, **required**)
- **Notes**: Side-effecting. Called from Telegram bot handler, not the agent loop.
- **Latency p50**: untested (mutating)

---

### instagram_publish_post  *(MUTATING — not called in read-only pass)*
- **Purpose**: Publish an approved post. Rejects if not yet approved.
- **Input schema**:
  - `scheduledPostId` (string, **required**)
- **Notes**: Side-effecting. Errors if `instagram_approve_post` not called first — enforce this gate in agent logic.
- **Latency p50**: untested (mutating)

---

### instagram_register_webhook  *(MUTATING — not called in read-only pass)*
- **Purpose**: Register a public URL to receive inbound Instagram DM and comment events.
- **Input schema**:
  - `url` (string, **required**): public HTTPS URL
- **Notes**: Side-effecting. Call alongside `whatsapp_register_webhook` at startup.
- **Latency p50**: untested (mutating)

---

### instagram_inject_dm  *(MUTATING — not called in read-only pass)*
- **Purpose**: Inject a simulated inbound DM from a fake follower (test/evaluator use).
- **Input schema**:
  - `threadId` (string, **required**)
  - `from` (string, **required**): IG handle of simulated follower
  - `message` (string, **required**)
- **Notes**: Side-effecting. Test helper analogous to `whatsapp_inject_inbound`.
- **Latency p50**: untested (mutating)

---

## Family: gb_*  (Google Business — 4 tools)

### gb_list_reviews
- **Purpose**: Return recent reviews on the Happy Cake US Google Business profile (seeded sandbox data).
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  [
    {"id": "rev_001", "rating": 5, "author": "M. R.", "text": "Best honey cake in the area...", "createdAt": "2026-04-21T14:30:00Z"},
    {"id": "rev_002", "rating": 4, "author": "J. S.", "text": "Lovely pistachio roll. Wish you delivered.", "createdAt": "2026-04-19T09:12:00Z"},
    {"id": "rev_003", "rating": 2, "author": "A. P.", "text": "Cake was fine but I waited 25 minutes for one slice...", "createdAt": "2026-04-15T17:45:00Z"}
  ]
  ```
  (4 reviews total; ratings: 5, 4, 2, 5)
- **Notes**: Read-only. Review IDs (`rev_001` through `rev_004`) are stable seeded values. Use `id` with `gb_simulate_reply`.
- **Latency p50**: ~219ms

---

### gb_get_metrics
- **Purpose**: Fetch sandbox Google Business metrics: views, calls, directions, website clicks.
- **Input schema**:
  - `period` (string, optional): `last_7_days | last_30_days`
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {
    "simulated": true, "period": "last_30_days",
    "profileViews": 1842, "searchViews": 1340, "mapViews": 502,
    "directionsRequests": 87, "callsClicks": 41, "websiteClicks": 96
  }
  ```
- **Notes**: Read-only. Static seeded data. Default period is `last_30_days`.
- **Latency p50**: ~209ms (fastest observed)

---

### gb_list_simulated_actions
- **Purpose**: Inspect everything this team has recorded in the Google Business simulation namespace.
- **Input schema**: none
- **Sample call**: `{}`
- **Sample response (success)**:
  ```json
  {"replies": [], "posts": []}
  ```
- **Notes**: Read-only. Audit view of all `gb_simulate_reply` and `gb_simulate_post` calls made by the team.
- **Latency p50**: ~230ms

---

### gb_simulate_reply  *(MUTATING — tested for failure shape only)*
- **Purpose**: Record a proposed reply to a Google review (simulated, does not actually post to Google).
- **Input schema**:
  - `reviewId` (string, **required**)
  - `reply` (string, **required**)
- **Sample response (not found / error)**:
  ```json
  {"content": [{"type": "text", "text": "Error: Review not found"}], "isError": true}
  ```
- **Notes**: Side-effecting. `reviewId` must be a valid ID from `gb_list_reviews` (e.g. `rev_001`). Evaluator checks both existence and wording of reply.
- **Latency p50**: ~220ms

---

### gb_simulate_post  *(MUTATING — not called in read-only pass)*
- **Purpose**: Record a proposed Google Business post (simulated).
- **Input schema**:
  - `content` (string, **required**)
  - `callToAction` (object, optional): `{label: string, url: string}`
  - `photoUrl` (string, optional)
- **Notes**: Side-effecting. Evaluator counts GB posts as part of channel response score.
- **Latency p50**: untested (mutating)

---

## Cross-cutting findings

### Auth
Single `X-Team-Token` header. All state (orders, tickets, campaigns, timelines) is namespaced per token. No OAuth, no per-resource tokens. Token is stable — store in env, never in source.

### Response envelope quirk
Every successful tool call returns:
```json
{"result": {"content": [{"type": "text", "text": "<JSON string or raw CSV>"}]}}
```
Callers must always do `json.loads(result["content"][0]["text"])` — except `square_recent_sales_csv` which returns raw CSV. Wrap in a helper that detects JSON vs CSV.

### Error shapes
Two distinct error levels:
1. **JSON-RPC level** (`result.error`): unknown tool name (`-32004`), unsupported method (`-32601`). Always a top-level `error` key.
2. **Tool level** (`result.isError: true`): logical errors like missing required arg, not-found records. Content text starts with `"Error: "`.

Quirk: some tools return empty arrays instead of errors for not-found (e.g. `square_get_inventory` with bad IDs, `marketing_get_campaign_metrics` with bad campaign ID, `instagram_send_dm` with bad threadId silently succeeds).

### Rate limits observed
None observed. 35 calls made in ~120 seconds with no 429 or throttle response.

### Latencies (p50)
- Fastest: `gb_get_metrics` ~209ms, `whatsapp_list_threads` ~218ms
- Typical: 220-260ms
- Slowest: `evaluator_generate_team_report` ~325ms
- All calls under 350ms. Budget ~300ms per call in agent loop.

### Missing tool families
None. All five families from the Team launch kit are present:
- `marketing_*` — 9 tools (confirmed)
- `kitchen_*` — 6 tools (confirmed)
- `square_*` — 7 tools (confirmed)
- `world_*` — 6 tools (confirmed)
- `evaluator_*` — 5 tools (confirmed)

Additional families not listed in the brief but present on the server:
- `whatsapp_*` — 4 tools
- `instagram_*` — 7 tools (includes schedule/approve/publish flow)
- `gb_*` (Google Business) — 5 tools

### Quirks and gotchas
1. `square_recent_sales_csv` returns raw CSV string, not JSON. All other tools return JSON-in-text.
2. `instagram_send_dm` accepts any `threadId` without error — no existence validation.
3. `marketing_get_campaign_metrics` returns empty array (not error) for unknown campaign IDs.
4. `evaluator_generate_team_report` accepts wrong types for optional fields without error (coerces silently).
5. `evaluator_score_world_scenario` gives 40/100 baseline just for having made MCP calls — server tracks all calls in `mcp_audit_log`. This means the eval is actively watching the team's tool usage.
6. `instagram_publish_post` will error if called before `instagram_approve_post` — enforce gate in agent.
7. No `resources/list` or `prompts/list` support — MCP capabilities are tools-only.
8. The server reported `capabilities.tools.listChanged: false` — tool list is static for the hackathon.
9. `kitchen_create_ticket` uses `productId` (e.g. `honey-cake-slice`) NOT `variationId` — different namespace than square catalog. Map via `kitchenProductId` field in `square_list_catalog` response.
