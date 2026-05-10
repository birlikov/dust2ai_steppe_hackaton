# Architecture — HappyCake AI

> Required by the hackathon brief §8. Documents the agent topology, MCP
> routing, owner controls, channel adapters, kitchen handoff, and the
> closed-loop marketing flow. Code is the source of truth; this file is a
> map.

## 1. Two-Claude pattern

| Layer | Identity | System prompt | Model | How it's invoked |
|---|---|---|---|---|
| **Dev Claude** | Project planner / coder / reviewer | `CLAUDE.md` + `.claude/agents/*.md` (planner, coder, tester, brief-analyst, mcp-recon, critic) | Whatever the developer is using locally | Claude Code CLI in this repo |
| **Runtime Claude** | The HappyCake assistant | `agent/{SOUL,RULES,TOOLS,EXAMPLES}.md` composed by `src/agents/system_prompt.py` | `claude-opus-4-7` (pinned) | `src/agents/claude_bridge.py` shells out to `claude -p --system-prompt …` with `ANTHROPIC_MODEL=claude-opus-4-7` and a formatted history block; **MCP plumbing is inherited from `.claude/settings.local.json`** so the runtime can call MCP tools without extra glue |

The bridge is a thin async subprocess wrapper, not a wrapper around the
Anthropic SDK. The brief disallows the SDK for the runtime path; `claude
-p` is the explicitly allowed alternative. There is no Anthropic API key
in `.env`; we removed the dependency from `pyproject.toml` in Phase 1.

## 2. End-to-end request flow

```
                   ┌─────────────────────────────────────────────────────┐
                   │                                                     │
   Telegram   ─────▶  aiogram bot (polling)        ──┐                   │
   (owner)         │  src/bot/app.py                  │                   │
                   │  + handlers, owner_commands,     │                   │
                   │    keyboards, middleware         │                   │
                   └────────────────┬─────────────────┘                   │
                                    │ /dashboard, /budget, /inbox,/notify │
                                    │ + free-text via bridge              │
                                    ▼                                     │
                   ┌────────────────────────────────────────────┐         │
                   │  ClaudeBridge        (src/agents/         │         │
                   │  + system_prompt.py)  claude_bridge.py)   │         │
                   │                                           │         │
                   │  composes agent/*.md  →  claude -p        │         │
                   │  --system-prompt …    runtime persona     │         │
                   └────────────────┬──────────────────────────┘         │
                                    │                                     │
                                    ▼                                     │
                   ┌────────────────────────────────────────────┐         │
                   │  Orchestrator       (src/workflows/         │         │
                   │  per-turn glue)     orchestrator.py)       │         │
                   │  • load history     • bridge.query         │         │
                   │  • voice-lint reply • audit + persist      │         │
                   └────────────────┬──────────────────────────┘         │
                                    │                                     │
   Website    ─────▶┌────────────────────────────────────────────┐         │
   (chat)          │  FastAPI app   (src/webhooks/app.py)        │◀────────┘
                   │  POST /api/chat  → Orchestrator → Bridge    │
                   │  GET  /api/catalog  → MCP square_list_*     │
                   │  GET  /api/policies → static (storefront.py)│
                   │  POST /api/lead   → drafts.insert_lead +    │
                   │                     marketing_report_to_owner│
                   └────────────────┬─────────────────────────────┘
                                    │
   World engine  ───┐              │
                    ▼              ▼
   ┌────────────────────────────────────────────┐
   │  WorldRunner      (src/world/runner.py)    │
   │  long-lived supervisor in the bot process; │
   │  restarts WorldPoller on error/quiet exit  │
   │     │                                      │
   │     ▼                                      │
   │  WorldPoller     (src/world/poller.py)     │
   │  drives world_next_event → channel handler │
   │  whatsapp_send / instagram_send_dm /       │
   │  instagram_reply_to_comment via MCP        │
   │  (off when WORLD_POLLER_ENABLED=false or   │
   │   ./scripts/run.sh --no-poller)            │
   └────────────────┬───────────────────────────┘
                    │
                    ▼
            ┌──────────────────────────────────────┐
            │  HappycakeMcpClient                  │
            │  (src/mcp/http_client.py)            │
            │  HTTPS + JSON-RPC 2.0                │
            │  X-Team-Token header                 │
            │  retry + envelope unwrap             │
            └────────────────┬─────────────────────┘
                             │
                             ▼
            https://www.steppebusinessclub.com/api/mcp
            55 tools across 8 families
              square_*, kitchen_*, marketing_*,
              world_*, evaluator_*,
              whatsapp_*, instagram_*, gb_*

   SQLite (data/state.db)
     sessions  fsm_state  audit_log  drafts
     idempotency_keys  owner_identity  leads
```

The same `Orchestrator` class serves the Telegram free-text handler, the
on-site chat widget (`POST /api/chat`), and every WhatsApp / Instagram
handler in `WorldPoller`. Channel-specific code only handles I/O.

## 3. The runtime personas — `agent/` and `owner_agent/`

We run **two** runtime personas. Each is four small files composed in
deterministic order (SOUL → RULES → TOOLS → EXAMPLES) into one
`--system-prompt` blob.

### 3.1 Customer persona — `agent/`

Used on the website chat widget, WhatsApp, Instagram, Google Business.
Loaded by `system_prompt.load_system_prompt()` and passed to
`build_default_bridge()`.

| File | Job |
|---|---|
| `agent/SOUL.md` | Identity, brand values, voice character. Distilled from `HCU_BRANDBOOK.md` §1 + §2. |
| `agent/RULES.md` | Hard rules (English-only, wordmark, cake-name placement, ≤3 emoji, MCP-first, no fabrication, kitchen-capacity precondition, owner-approval gate, never delete a comment) + soft rules + escalation triggers. |
| `agent/TOOLS.md` | When-to-use guidance for every MCP tool, organised by family. Sourced from `docs/mcp_inventory.md`. |
| `agent/EXAMPLES.md` | Reference posts (brandbook Appendix C) + reply templates by interaction shape. |

### 3.2 Owner persona — `owner_agent/`

Used on the Telegram bot (free-text + slash-command summaries +
proactive notifier). Loaded by `system_prompt.load_owner_system_prompt()`
and passed to `build_owner_bridge()`. The customer persona is **never**
used on Telegram — different audience, different rules.

| File | Job |
|---|---|
| `owner_agent/SOUL.md` | Operations-assistant identity. Terse, business-aware, surfaces what needs attention. |
| `owner_agent/RULES.md` | No JSON in messages; numbers in English; ≤4 short bullets; ask before mutating; escalate uncertainty; never delete a customer comment. |
| `owner_agent/TOOLS.md` | Same MCP catalog as `agent/TOOLS.md` but reframed for ops use ("when the owner asks for sales today, call `square_get_pos_summary` and report orders + revenue + channel mix in two sentences"). Mutating channel tools require owner instruction in the same turn — otherwise the existing drafts approval queue. |
| `owner_agent/EXAMPLES.md` | Sample owner Q&A (sales today, anything urgent, what's pending). |

Each file is independently editable and reviewable. The composer
(`src/agents/system_prompt.py`) caches each persona separately — restart
the bot to pick up edits to either.

### 3.3 Proactive notifier — `src/bot/notifier.py`

An asyncio task running on `NOTIFIER_INTERVAL_S` (default 1800 s). Each
tick: pull MCP state, diff against the previous tick's snapshot, and if
anything material changed (new orders, new pending drafts, kitchen
filling up) ask the owner-bridge for a 1-2 line English brief and push
it to the owner's Telegram chat. Idle ticks stay silent. The task is
cancellation-safe and never crashes the polling loop on errors.

### 3.4 Always-on world poller — `src/world/runner.py`

Sister task to the notifier, also in the bot process. The simulator
emits inbound WhatsApp / Instagram messages on the team timeline —
visible via `world_next_event`. `WorldRunner` is a thin supervisor
around `WorldPoller`: it spins the poller in a restart loop with
bounded exponential backoff so transient MCP errors don't kill the
listener. Each event is dispatched to the same `Orchestrator` the web
chat uses, and the reply is posted via the channel-appropriate MCP
tool (`whatsapp_send`, `instagram_send_dm`, `instagram_reply_to_comment`).
Set `WORLD_POLLER_ENABLED=false` in `.env` (or run
`./scripts/run.sh --no-poller`) to disable it — required when running
`scripts/run_scenario.py` against the same team token, since two
consumers would race on `world_next_event`.

## 4. Owner-side Telegram bot

Owner-facing only. The customer-facing replies happen on
WhatsApp / Instagram / the website chat widget; the bot is for control,
visibility, and approvals. Commands:

| Command | Implementation | Demonstrates |
|---|---|---|
| `/start` | `src/bot/handlers.py::cmd_start` — captures owner chat id idempotently into `owner_identity` SQLite table | First-run setup; survives restart |
| `/help` | static command listing | Operator UX baseline |
| `/dashboard` | `src/bot/owner_commands.py::cmd_dashboard` — calls `square_get_pos_summary`, `kitchen_get_production_summary`, `evaluator_get_evidence_summary` | Live MCP-grounded snapshot |
| `/budget` | `cmd_budget` — `marketing_get_budget` + `marketing_get_campaign_metrics` + recent leads from SQLite | Marketing $500 visibility |
| `/inbox` | `cmd_inbox` (alias `/drafts`) — lists pending **marketing drafts** with **Approve / Edit / Reject** inline keyboard. Customer orders are auto-confirmed and not queued here. Approve drives `instagram_approve_post` + `instagram_publish_post` for IG drafts | Brandbook §7 approval gate |
| `/notify` | `cmd_notify` — sets the proactive-update cadence per owner (`/notify 1m`, `/notify 30m`, `/notify 2h`, `/notify off`, `/notify on`). Persists to `owner_identity.notifier_interval_s`; `notifier.py` reads the per-owner value each tick and falls back to env default when NULL | Operator-tuneable cadence; respects "don't ping me too often" |
| `/cancel`, `/restart` | clear FSM, message ack | Operator UX safety |
| free text | message handler injects `bridge: ClaudeBridge`; orchestrator runs the same path as customer channels. Replies go through `tg_normalise()` (`src/bot/markdown.py`) which converts CommonMark `**bold**` → Telegram-classic `*bold*` so the persona's bolds actually render | Persona smoke / debug |

FSM state persists in `data/state.db` (`fsm_state` table) so a process
restart doesn't lose mid-flow context. Every inbound message goes through
`AuditMiddleware` which records to `audit_log`.

## 5. Channel adapters

| Surface | Inbound | Outbound | Approval gate |
|---|---|---|---|
| Website chat | `POST /api/chat` (FastAPI, `src/webhooks/app.py`) | response body | none — runtime persona is brand-voice-linted |
| WhatsApp | `world_next_event` (sandbox) → `WorldPoller._handle_whatsapp` | `whatsapp_send` MCP | none for DMs (per brandbook §7); orders create `kitchen_create_ticket` which is owner-visible via `/dashboard` |
| Instagram DM | same poller → `_handle_instagram_dm` | `instagram_send_dm` | none for DMs |
| Instagram comment | same poller → `_handle_instagram_comment` | `instagram_reply_to_comment` | none |
| Instagram feed posts | `seed_drafts.py` → `instagram_schedule_post` → `drafts` table | owner taps Approve in `/inbox` → `instagram_approve_post` → `instagram_publish_post` | **required** (brandbook §7) |
| Google Business reviews | `seed_review_replies.py` → `gb_list_reviews` | bridge generates reply → `gb_simulate_reply` | logged but not gated; brandbook says *every review answered* |
| Google Business posts | (Phase 4+) | `gb_simulate_post` | required (treat like IG posts) |
| Lead form | `POST /api/lead` from Astro storefront | persists to `leads` SQLite + best-effort `marketing_report_to_owner` | none — leads always captured |

## 6. POS + kitchen handoff

Order flow (when the runtime persona accepts an order in chat):

1. Runtime calls `square_list_catalog` to confirm the item exists.
2. Runtime calls `kitchen_get_capacity` (and where product-specific timing matters, `kitchen_get_menu_constraints`) — this is the **kitchen-capacity precondition** in `agent/RULES.md` rule 7.
3. Runtime calls `square_create_order` with `items[{variationId, quantity}]`, `source` (`whatsapp` | `instagram` | `website` | `walk-in` | `agent`), and `customerName`. Returns `orderId`.
4. Runtime calls `kitchen_create_ticket` with `orderId`, `customerName`, `items[{productId, quantity}]` — **`productId` ≠ `variationId`** (mapping via `kitchenProductId` in catalog).
5. Kitchen-side flow (out of scope for the runtime; owner / dispatcher drives it): `kitchen_accept_ticket` → `kitchen_mark_ready` (or `kitchen_reject_ticket` if infeasible).
6. **Owner notification (best-effort):** after step 4 succeeds (or `kitchen_pending` when step 4 fails) `_notify_owner_of_order` in `src/webhooks/app.py` opens a one-shot aiogram `Bot`, looks up the paired owner in `owner_identity`, and sends a one-line summary with channel-aware emoji (`📦 website`, `💬 whatsapp`, `📸 instagram`, `🤖 agent`, `🚶 walk-in`), brand-correct cake names, total, and pickup/delivery time. Failures log a warning and never block the customer order.

The runtime never short-circuits step 2. The brand-voice linter
(`src/core/voice.py`) warns on missing-evidence patterns at the reply
level; the audit log is the proof a tool was actually called.

## 7. Marketing $500 → $5,000 closed loop

`docs/MARKETING_PLAN.md` is the human-facing plan;
`scripts/seed_marketing.py` is the executable mirror. Each run:

```
marketing_get_budget                           ← anchor at $500
   │
   ▼
marketing_create_campaign  (× 2 channels)
   │  Mother's Day Meta Ads
   │  Local-search Google Ads
   ▼
marketing_launch_simulated_campaign
   │
   ▼
marketing_generate_leads
   │
   ▼
marketing_route_lead  (× per lead)             ← always with a reason
   │  routeTo: instagram | website | whatsapp | owner_approval
   ▼
marketing_adjust_campaign                      ← evidence of closed loop
   │
   ▼
marketing_get_campaign_metrics
   │
   ▼
marketing_report_to_owner                      ← evaluator scores this
```

Attribution back to the storefront: every campaign URL carries
`?utm_source=…&utm_campaign=…`. The Astro forms (`/order`, `/custom`)
forward both to `/api/lead`, which persists them to the `leads` table and
calls `marketing_report_to_owner`. The evaluator can read the loop end to
end via `evaluator_score_marketing_loop` (the `gaps` array tells you
exactly what step is missing).

## 8. Storage model

Single SQLite database (`data/state.db`) with WAL mode and a one-process
connection. Migrations under `config/migrations/` apply on first
connection.

| Table | Purpose |
|---|---|
| `schema_version` | Migration tracking |
| `sessions` | `(channel, external_id) → session id`, JSON `state` blob (history, FSM bits) |
| `fsm_state` | aiogram FSM backing |
| `idempotency_keys` | Cache of mutating tool-call results, keyed for safe retry |
| `audit_log` | Append-only log of every inbound, tool call, tool result, outbound, world event, error |
| `drafts` | Approval queue (`pending` → `approved`/`edited`/`rejected` → `published`) |
| `owner_identity` | Single-row table — owner Telegram chat id captured on first `/start` |
| `leads` | Inbound leads from `/api/lead`, with utm attribution |

## 9. Agent-friendliness surfaces

| Surface | Where it lives |
|---|---|
| Schema.org `Product` + `Offer` JSON-LD | `web/src/pages/cake/[slug].astro` (every product page) |
| Machine-readable catalog | `web/src/pages/catalog.json.ts` mirrors `/api/catalog` shape |
| Policies (English plain-text) | `web/src/pages/policies.astro` + `/api/policies` JSON form |
| Predictable URLs | `/cake/[slug]`, `/policies`, `/order`, `/custom`, `/about`, `/guides/cake-for-x-guests` |
| `robots.txt` | `web/public/robots.txt` (allows everything; sitemap pointer) |
| `sitemap.xml` | `web/src/pages/sitemap.xml.ts` (server-rendered; lists all routes + product slugs from catalog) |
| Order-intent path | `/order?slug=…` lead form, ≤3 clicks from any product page |

## 10. Quality gates

- `ruff check src tests scripts examples` — clean
- `mypy --strict src` — clean (40 source files)
- `pytest -q` — 103 tests green
- Pre-commit hook (in `.git/hooks/pre-commit`) runs all three before allowing a commit
- `web/`: `npm run build` exits 0, `tsc --noEmit` clean

## 11. What's deliberately out of scope

- Real Square / Stripe / payment integration (brief §4 forbids real payment credentials).
- Real Meta / Google Ads spend (brief §4; we run through `marketing_*` simulator).
- Multi-language site copy or replies (brand.r1: English only).
- Multi-tenant auth (sandbox is single-tenant per `X-Team-Token`).
- LLM fine-tuning (brief: Opus 4.7 + good prompts + tools is the standard).
- Microservices / k8s / multi-region (single process, single host).

## 12. Repository layout

```
agent/        Runtime persona — composed system prompt for `claude -p`
src/
  agents/     ClaudeBridge subprocess shim + system-prompt composer
  bot/        aiogram Telegram handlers, owner commands, FSM, middleware
  webhooks/   FastAPI app: webhook receiver + storefront API + chat
  mcp/        HappycakeMcpClient (HTTPS+JSON-RPC) + registry (stdio/SSE)
  workflows/  Orchestrator — channel-agnostic per-turn glue
  world/      WorldPoller (one-shot drain) + WorldRunner (always-on supervisor)
  storage/    SQLite repos (sessions, drafts, leads, audit, idempotency)
  core/       Config, logging, errors, idempotency, retry, voice linter
  scenarios/  YAML acceptance harness (kept for unit-style smoke)
tests/
  unit/       103 pytests across 13 modules
  integration/ end-to-end through bot + MCP (kept for future scenarios)
  scenarios/  YAML acceptance criteria
web/
  src/        Astro pages, layouts, lib/api.ts, chat-widget script
  public/     robots.txt, chat-widget.js, brand assets (copied at build)
docs/
  PLAN.md             live execution plan + locked decisions
  specs.md            brief-analyst output (60 ACs)
  mcp_inventory.md    mcp-recon output (55 tools)
  CONTRACTS.md        web ↔ backend API contract
  MARKETING_PLAN.md   $500 → $5,000 plan
  DEMO.md             clean-clone runbook
  critic_report.md    Phase 4 critic scorecard
  decisions.md        ADR log
config/
  .env.example        secrets template (placeholders only)
  mcp.json            MCP config for stdio/SSE servers
  migrations/         SQL migrations
scripts/
  run_scenario.py     world-engine driver + self-grade
  seed_marketing.py   $500 marketing loop end-to-end
  seed_review_replies.py  brand-voice GB review replies
  seed_drafts.py      IG post drafts seeded for /inbox approval
  demo.sh             single-shot orchestrator (the submission demo)
  start_tunnel.sh     ngrok tunnel
HACKATHON_BRIEF.md    the unsealed brief (verbatim)
HCU_BRANDBOOK.md      the brand book (source of truth for voice + rules)
assets/brand/         photographs, logo, social crops (no AI imagery)
```
