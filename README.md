# HappyCake AI — Steppe Business Club hackathon submission

> An AI-assisted sales and operations system for **HappyCake US** (Sugar
> Land, TX cake business). Submission for the Steppe Business Club
> *Agentic AI for Real Business* hackathon (May 9–10, 2026).
>
> One persona, every customer touchpoint: storefront chat, WhatsApp,
> Instagram. One owner cockpit: Telegram. Every customer-facing claim is
> grounded in a live MCP tool call. **Runtime model**: `claude-opus-4-7`
> via the `claude` CLI subprocess (no Anthropic SDK in production).
> **MCP server**: hosted by Steppe Business Club; 55 tools across 8
> families.

## TL;DR — what to test

After running `./scripts/run.sh` you have three things to try:

1. **Storefront + on-site chat** — the script prints a public ngrok HTTPS
   URL; open it, browse the catalog, ask the chat widget about prices,
   timing, allergens, custom orders.
2. **Owner cockpit** — DM `@happycake_agent_bot` on Telegram, send
   `/start` (the bot prompts for the passphrase set in `.env`), then try
   `/dashboard`, `/budget`, `/inbox`, `/notify 30m`, or just type a
   free-text question.
3. **Persona-driven channel coverage** —
   `uv run python scripts/test_persona_channels.py` runs WhatsApp +
   Instagram + Google Business through the live runtime persona on the
   live MCP and writes a scorecard to `data/scorecard_persona_*.json`.

## Quickstart

```bash
git clone <this-repo> hackaton && cd hackaton
cp config/.env.example .env
# Fill TELEGRAM_BOT_TOKEN and SBC_TEAM_TOKEN — both are required.
./scripts/run.sh                  # full demo (bot + storefront + ngrok)
# ./scripts/run.sh --no-bot       # storefront + ngrok only
# ./scripts/run.sh --no-ngrok     # local dev on :8000
```

`./scripts/run.sh` validates `.env`, regenerates `.mcp.json`, runs
`uv sync`, builds the Astro storefront, launches FastAPI on `:8000`,
starts the bot, and opens an ngrok tunnel. The `claude` CLI must be on
`PATH` (it provides the runtime LLM via the user's Max subscription —
the brief explicitly disallows the Anthropic SDK in production).

## What's wired

Six outcomes from brief §3, all served by the same MCP-grounded runtime
persona:

| # | Outcome | Where it lives | Key tools |
|---|---|---|---|
| 1 | Website / storefront | `web/` (Astro + Tailwind) → `/api/catalog` + `POST /api/chat` + `POST /api/order` | `square_list_catalog`, `kitchen_get_capacity` |
| 2 | Agent-friendly site | JSON-LD `Product` + `Offer` per product page; `/api/catalog`, `/sitemap.xml`, `/robots.txt`, `/agent.txt` (machine-readable index for crawling agents); predictable URLs | (read-only artefacts) |
| 3 | On-site assistant | Floating cashier widget → `POST /api/chat` → orchestrator → `claude -p` (with MCP). Cart-aware: knows what's in the basket and can place orders end-to-end | every relevant family |
| 4 | WhatsApp | `WorldPoller` consumes `world_next_event` → orchestrator → `whatsapp_send`. Accepted orders auto-fire `square_create_order` + `kitchen_create_ticket` and push a one-line `📦` summary to the owner Telegram chat | `square_create_order`, `kitchen_create_ticket`, `whatsapp_send` |
| 5 | Instagram | DMs + comments through the same poller; feed-post drafts go through `/inbox` (Approve / Edit / Reject inline keyboard) per brandbook §7 | `instagram_send_dm`, `instagram_reply_to_comment`, `instagram_schedule_post`, `instagram_approve_post`, `instagram_publish_post` |
| 6 | $500 marketing plan + channel coverage | `docs/MARKETING_PLAN.md` (human plan) + `scripts/seed_marketing.py` (executable closed loop) + `scripts/test_persona_channels.py` (WA + IG + GB through the runtime persona end-to-end) | full `marketing_*` family + `evaluator_score_*` |

Customer orders are **auto-confirmed** on the `POST /api/order` path —
the owner does not gate them. `/inbox` is reserved for marketing posts
(IG captions, GB posts, paid-ad creatives) where brandbook §7 requires
owner approval.

## Owner controls (Telegram bot, `@happycake_agent_bot`)

| Command | What it does |
|---|---|
| `/start` | Pair this Telegram chat as the owner (gated by passphrase in `.env`); from then on, order-push and `/inbox` notifications land here. |
| `/help` | Lists every command and how to use it. |
| `/dashboard` | One-screen view: today's sales mix, kitchen utilisation, urgent items, drafts pending. |
| `/budget` | Marketing budget remaining + recent attributed leads. |
| `/inbox` (alias `/drafts`) | Marketing posts queued for Approve / Edit / Reject. Survives bot restart (SQLite). |
| `/notify` | Set push interval (`/notify 1m`, `/notify 30m`, `/notify 2h`, `/notify off`, `/notify on`). |
| `/cancel` | Cancel the current step. |
| `/restart` | Wipe conversation memory for this chat. |

Free-text DMs go through the same orchestrator the customer-facing
channels use, with the owner-side persona (`owner_agent/*.md`) loaded
instead of the customer one.

## Architecture in one paragraph

We run **two Claudes**. Dev Claude (this repo's `CLAUDE.md`) plans,
codes, reviews. Runtime Claude — the customer-facing HappyCake assistant
— has its system prompt composed from four small files under `agent/`
(SOUL, RULES, TOOLS, EXAMPLES) and is invoked by
`src/agents/claude_bridge.py` shelling out to
`claude -p --system-prompt …` with `ANTHROPIC_MODEL=claude-opus-4-7`.
The owner-facing variant is composed the same way from `owner_agent/`.
The bridge inherits MCP plumbing from `.claude/settings.local.json`, so
the runtime can call MCP tools directly. Every channel (Telegram,
WhatsApp, Instagram, website chat, world events) routes through one
`Orchestrator` that adds session history, brand-voice lint, and an
audit-log entry. Full diagram in **`ARCHITECTURE.md`**.

## Live evidence

Latest persona-channel scorecard
(`data/scorecard_persona_20260510T024005Z.json`, generated by
`scripts/test_persona_channels.py` against the live MCP):

| Dimension | Score | Note |
|---|---|---|
| `evaluator_score_channel_response` | **80 / 100** | Brand-correct replies on WA, IG, GB — generated by the runtime persona, not canned strings |
| `evaluator_score_world_scenario` | **100 / 100** | 9 events in timeline, 6 delivered, 200 audit calls |
| `whatsappInbound` | 8 | Live world events drained by `WorldPoller` |
| `auditCalls` | 200 | MCP-call evidence |

Outbound channel counters are credited via the evaluator score, not raw
counts (see `docs/SUBMISSION_EVIDENCE.md` for the per-channel excerpts +
proof points). To repeat:
`uv run python scripts/test_persona_channels.py`.

## Repo layout

```
agent/             Customer-facing runtime persona (SOUL, RULES, TOOLS, EXAMPLES)
owner_agent/       Owner-facing persona — same shape
src/               Application code (agents, bot, webhooks, mcp, workflows, storage, core)
web/               Astro + Tailwind storefront with cart-aware chat widget
tests/             pytest unit + integration + scenario YAML
scripts/           run.sh, demo.sh, seed_marketing.py, test_persona_channels.py, …
docs/              ARCHITECTURE link target, PLAN, specs, MCP inventory, DEMO, MARKETING_PLAN, SUBMISSION_EVIDENCE
config/            .env.example, .mcp.json template
assets/            Brand assets (palette, photography references)
data/              Runtime artefacts (gitignored: state.db, scorecards, logs)
HACKATHON_BRIEF.md The unsealed brief, verbatim
HCU_BRANDBOOK.md   Brand voice, palette, hard rules — the runtime's source of truth
```

## Hackathon brief compliance (per `HACKATHON_BRIEF.md` §8)

| Deliverable | Where |
|---|---|
| README, setup from a fresh clone | This file + `./scripts/run.sh` |
| `ARCHITECTURE.md` — agents, routing, MCP usage, owner-bot mapping | `ARCHITECTURE.md` |
| `.env.example` with placeholders only | `config/.env.example` |
| Website / storefront instructions | `web/README.md` + `docs/DEMO.md` |
| Production / local deploy notes | `docs/DEMO.md` |
| Business-impact hypothesis + $500 marketing case | `docs/MARKETING_PLAN.md` |
| Agent-friendly website notes | `web/public/agent.txt` + JSON-LD per page + `/api/catalog` |
| On-site assistant test script | `docs/DEMO.md` + `scripts/test_persona_channels.py` |
| Telegram bots and what each does | "Owner controls" table above |

## License

MIT — see `LICENSE`.
