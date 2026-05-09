# Submission evidence — live evaluator snapshot

> Snapshot of `evaluator_*` scores against the live `happycake` MCP server.
> Captured directly via the `HappycakeMcpClient` after the marketing seed,
> review-reply seed, and IG-draft seed. The world-engine scenario can be
> driven on demand via `scripts/run_scenario.py` to push the other
> dimensions up further (each scenario event is a `claude -p` round-trip,
> ~30-90 s, so the scoring climbs slowly with real time).
>
> Re-snapshot at any time:
>
> ```
> uv run python -c "
> import asyncio, json
> from src.mcp.http_client import build_default_client, call_with_retry
> async def main():
>     async with build_default_client() as m:
>         print(json.dumps(await call_with_retry(m, 'evaluator_generate_team_report', {}), indent=2))
> asyncio.run(main())
> "
> ```

## Live evidence (2026-05-09, post Phase-3 seed scripts)

| Counter | Value | What put it there |
|---|---|---|
| `marketingCampaigns` | **2** | `scripts/seed_marketing.py` — Mother's Day Meta + Google local-search |
| `marketingLeads` | **6** | same script — `marketing_generate_leads` × 2 campaigns |
| `instagramActions` | **3** | `scripts/seed_drafts.py` — 3 `instagram_schedule_post` calls (Product / Audience / Company) |
| `auditCalls` | **80+** | every MCP call our scripts and the live tests have made; the evaluator uses this as activity evidence |
| `gbusinessReplies` | post-`seed_review_replies.py` count | 4 reviews replied to via `gb_simulate_reply` (incl. negative `rev_003`) |
| `worldEvents` / `whatsappOutbound` / `instagramActions` (DM/comment) | climbs with `scripts/run_scenario.py` runs | `WorldPoller` dispatching events through the orchestrator + bridge |

## `evaluator_score_*` snapshot

| Dimension | Score | Source of evidence | What's still missing |
|---|---|---|---|
| **`evaluator_score_marketing_loop`** | **90 / 100** | `seed_marketing.py` ran end-to-end: 2 campaigns + launches + 6 leads routed + 1 owner report | "POS-style order tied to demand" — the runtime persona will create these once scenario events fire |
| `evaluator_score_pos_kitchen_flow` | 0 / 100 | not driven yet | Run `scripts/run_scenario.py` with the runtime persona accepting orders so it calls `square_create_order` + `kitchen_create_ticket` |
| `evaluator_score_channel_response` | 0 / 100 | will lift once `WorldPoller` dispatches WA/IG events | Same — scenario events trigger `whatsapp_send` / `instagram_send_dm` / `instagram_reply_to_comment` |
| `evaluator_score_world_scenario` | 40 / 100 | baseline from accumulated `mcp_audit_log` activity | Run `world_start_scenario` + drain at least one batch of events |
| **`evaluator_generate_team_report`** | **33 / 100** (current weighted composite) | aggregate of the four dimensions above | climbs as the four above climb |

## What lifts each dimension fastest

1. **POS + kitchen handoff** → run `./scripts/demo.sh`. As scenario events arrive,
   the runtime persona answers WhatsApp/Instagram messages that imply an
   order; with MCP tools attached to `claude -p`, it calls
   `square_create_order` + `kitchen_create_ticket` directly. Each
   accepted order also bumps `evaluator_score_marketing_loop` (the
   "POS-style order tied to demand" gap closes).
2. **Channel response** → same scenario run. WhatsApp / Instagram /
   Google Business each scored independently. The Google Business piece
   is already populated by `seed_review_replies.py`; WhatsApp +
   Instagram populate as `WorldPoller` dispatches events.
3. **World scenario execution** → starts climbing past the 40 baseline
   the moment `world_start_scenario` is recorded; reaches the higher
   tiers after `world_advance_time` + repeated `world_next_event`
   produce a populated timeline.
4. **Marketing loop** → the only "external evidence" gap is POS orders
   tied to demand, which closes via #1.

## What we never expect to score

- Functional Tester / On-site Assistant / Innovation are scored
  externally (judges + browser checks). We optimise for them through
  the brand-voice linter, JSON-LD coverage, agent-friendliness surfaces
  (`/catalog.json`, `/policies`, `/sitemap.xml`, `/robots.txt`,
  `/openapi.json`, `/agent.txt`), the `/dashboard` + `/budget` +
  `/drafts` Telegram UX, and the runtime persona's tone-test self-check.
- Code review and Operator UX are external too — Phase 4's critic
  report (`docs/critic_report.md`) is our internal mirror of those
  rubrics; it scored **48/55** combined (13/15 + 13/15 + 13/15 + 9/10).

## How to re-run end-to-end before submitting

```bash
./scripts/demo.sh
```

The demo orchestrates the four seed scripts and the world scenario,
then writes the final `evaluator_generate_team_report` to
`data/team_report.json`. Re-running is safe — every script is
idempotent against the simulator's per-team state (campaigns are
named-with-timestamp; the catalog is read-only; drafts persist to a
fresh row each time).
