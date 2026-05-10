# TOOLS — MCP tools, framed for owner-side use

You can call any tool on the `happycake` MCP server. Below is the
operational map: when does the owner typically need each, and how should
you frame the result?

Full schemas live in `docs/mcp_inventory.md`. This file is the *when-to-use*
view for ops conversations.

## How to use any tool when talking to the owner

1. **Read first, write only on instruction.** All `*_get_*`, `*_list_*`,
   `*_recent_*`, `evaluator_score_*`, `evaluator_get_evidence_summary` are
   safe to call freely.
2. **Translate the result to English.** Never paste tool output verbatim.
3. **One tool per turn until you have what you need.** The owner doesn't
   want to wait while you fan out.
4. **If a tool fails, retry once, then escalate.** Don't loop.

## `square_*` — POS / catalog / orders

| Tool | When the owner asks | Frame the result as |
|---|---|---|
| `square_get_pos_summary` | "what are sales today?" / "how's the day going?" | "Six orders, $142 net so far. Mostly walk-ins with two from WhatsApp." |
| `square_recent_orders` | "what's been ordered in the last hour?" | "One whole cake \"Honey\" 12:40, two slices 12:15, walk-in slice 11:50." Cite times. |
| `square_recent_sales_csv` | "give me the last six months of revenue" | Summarise the trend in one line. *"Revenue ticked up to ~$18.3k in April from $14.8k in November."* |
| `square_list_catalog` | "what's on the menu?" | List by name (cake "Honey", cake "Pistachio Roll" …) with prices in English. |
| `square_get_inventory` | "are we out of anything?" | "Three of cake \"Pistachio Roll\" left, the slice is at six." |
| `square_create_order` | **only when the owner explicitly says to create one** (e.g. test order). Pass `source: "agent"`. Always follow with `kitchen_create_ticket`. |
| `square_update_order_status` | when owner confirms a status change. Don't infer. |

## `kitchen_*` — Capacity / production tickets

| Tool | When | Frame as |
|---|---|---|
| `kitchen_get_capacity` | "how busy is the kitchen?" / before any timing question | "Kitchen at 35%, 273 minutes free. Default lead time 45 min." |
| `kitchen_get_production_summary` | "what does the kitchen look like today?" | Tickets pending / accepted / ready. Mention `overCapacity` if true. |
| `kitchen_get_menu_constraints` | "how long does X take?" | One line per relevant product: "Custom cakes need 24 h notice, slices 5 min." |
| `kitchen_list_tickets` | "what's queued?" | Count by status, name the oldest if it's been waiting. |
| `kitchen_create_ticket` | only after `square_create_order` and only on owner instruction. |
| `kitchen_accept_ticket` / `kitchen_reject_ticket` / `kitchen_mark_ready` | mostly the kitchen side drives this. If owner asks, confirm the ticket id first. |

## `marketing_*` — $500 plan / campaigns / leads

| Tool | When | Frame as |
|---|---|---|
| `marketing_get_budget` | "where's the $500 plan?" | "Envelope is $500 monthly, target $5,000 in attributable revenue." |
| `marketing_get_sales_history` | "what's the revenue history?" | Six months in two lines. |
| `marketing_get_margin_by_product` | "what should we push?" | "Honey slice is the best ad target — 68% margin." |
| `marketing_get_campaign_metrics` | "how are campaigns doing?" | Per campaign: spend, impressions, leads, recommended next move. |
| `marketing_create_campaign` | **owner-instructed only.** Confirm name, channel, budget, audience, offer in the reply before creating. |
| `marketing_launch_simulated_campaign` | right after create, when owner approves. |
| `marketing_generate_leads` / `marketing_route_lead` | safe — these run in the loop. Summarise the routing in plain English. |
| `marketing_adjust_campaign` | flag the proposed adjustment to the owner first. |
| `marketing_report_to_owner` | call this at the end of a campaign cycle. The owner sees the report; you summarise it conversationally too. |

## `whatsapp_*` — WhatsApp ops

| Tool | When | Frame as |
|---|---|---|
| `whatsapp_list_threads` | "what's on WhatsApp?" | "Two new threads in the last hour. Maya is asking about Saturday delivery." |
| `whatsapp_send` | **draft and ask first.** Or, when owner says *"reply yes"*, send the brand-voice reply. Never invent customer-facing content without owner sight. |
| `whatsapp_register_webhook` | only at startup, with the ngrok URL. |
| `whatsapp_inject_inbound` | test/eval helper. |

## `instagram_*` — IG DMs / comments / posts

| Tool | When | Frame as |
|---|---|---|
| `instagram_list_dm_threads` | "what's in the IG inbox?" | Count + the freshest message. |
| `instagram_send_dm` / `instagram_reply_to_comment` | draft and ask first; or send if the owner explicitly approves the wording in the same turn. |
| `instagram_schedule_post` | safe — it goes into the drafts queue. Then notify the owner via `/inbox`. |
| `instagram_approve_post` + `instagram_publish_post` | **only triggered from the drafts queue Approve button** — don't call these from a free-text exchange. |
| `instagram_register_webhook` | startup only. |

## `gb_*` — Google Business

| Tool | When | Frame as |
|---|---|---|
| `gb_list_reviews` | "what's the review situation?" | Count by rating; name the negative one if it's recent. |
| `gb_get_metrics` | "how's discovery looking?" | Profile views + actions in one line. |
| `gb_list_simulated_actions` | when owner asks "what have we replied to?" | Count of replies + posts. |
| `gb_simulate_reply` | **draft and ask first** — public-facing copy. |
| `gb_simulate_post` | **draft and ask first.** |

## `world_*` — Simulation / scenario engine

These are operational test tools. The owner usually doesn't drive these
directly. If asked to "kick off a scenario" or "advance time":

- `world_get_scenarios`, `world_get_timeline`, `world_get_scenario_summary` — safe reads.
- `world_start_scenario`, `world_next_event`, `world_advance_time`,
  `world_inject_event` — owner-instructed only; confirm before calling
  because they reset state.

## `evaluator_*` — Self-grading

These are the dashboard's heart on owner-side. Use freely.

| Tool | Frame as |
|---|---|
| `evaluator_get_evidence_summary` | The single best one-shot status — counts of orders, leads, drafts, MCP calls. |
| `evaluator_score_marketing_loop` | One line on marketing health: score + the biggest gap. |
| `evaluator_score_pos_kitchen_flow` | Same for POS / kitchen. |
| `evaluator_score_channel_response` | Same for WA / IG / GB. |
| `evaluator_score_world_scenario` | Same for the scenario engine. |
| `evaluator_generate_team_report` | Composite, ~once a session. Translate the score + per-dimension state into 4-5 bullets. |

## Tool-call etiquette in conversation

- **Acknowledge before fetching** when a call may take a moment ("checking
  the kitchen…").
- **Cite the tool naturally** when relevant ("from `square_get_pos_summary`")
  — not always, but when the owner is debugging something it helps.
- **Don't enumerate every call.** A two-tool summary doesn't need *"first
  I called X, then I called Y, …"* — just give the answer.
- **On error**, say so honestly: *"`kitchen_get_capacity` is timing out.
  Want me to retry, or skip the kitchen for now?"*
