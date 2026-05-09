# HappyCake AI — Steppe Business Club hackathon submission

> An AI-assisted sales and operations system for **HappyCake US** (Sugar
> Land, TX cake business). Submission for the Steppe Business Club
> *Agentic AI for Real Business* hackathon (May 9–10, 2026).
>
> **Repo**: public on submission. **Runtime model**: `claude-opus-4-7` via
> the `claude` CLI (no Anthropic SDK in production). **MCP server**:
> hosted by Steppe Business Club; 55 tools across 8 families.

## What this submits

Six outcomes drawn from brief §3, all wired to the same MCP-grounded
runtime persona:

| # | Outcome | Where it lives | Key tools |
|---|---|---|---|
| 1 | Website / storefront | `web/` (Astro + Tailwind, 8 routes) → `/api/catalog` | `square_list_catalog`, `kitchen_get_capacity` |
| 2 | Agent-friendly site | JSON-LD `Product` + `Offer` per product page; `/catalog.json`, `/policies`, `/sitemap.xml`, `/robots.txt`; predictable URLs | (read-only artefacts) |
| 3 | On-site assistant | Floating chat widget → `POST /api/chat` → orchestrator → `claude -p` (with MCP) | every relevant family |
| 4 | WhatsApp | `WorldPoller` consumes `world_next_event` → orchestrator → `whatsapp_send`; orders create POS + kitchen tickets | `square_create_order`, `kitchen_create_ticket`, `whatsapp_send` |
| 5 | Instagram | DMs + comments through the poller; feed posts go through the **drafts approval queue** in Telegram | `instagram_send_dm`, `instagram_reply_to_comment`, `instagram_schedule_post`, `instagram_approve_post`, `instagram_publish_post` |
| 6 | $500 marketing plan | `docs/MARKETING_PLAN.md` (human plan) + `scripts/seed_marketing.py` (executable closed loop) | full `marketing_*` family + `evaluator_score_marketing_loop` |

The owner controls everything from one Telegram bot:
`/dashboard`, `/budget`, `/drafts` (Approve / Edit / Reject inline
keyboard), plus `/help`, `/start`, `/cancel`, `/restart`.

## Architecture in one paragraph

We run **two Claudes**. Dev Claude (this repo's CLAUDE.md) plans, codes,
reviews. Runtime Claude — the customer-facing HappyCake assistant — has
its system prompt composed from four small files under `agent/` (SOUL,
RULES, TOOLS, EXAMPLES) and is invoked by `src/agents/claude_bridge.py`
shelling out to `claude -p --system-prompt …` with `ANTHROPIC_MODEL=claude-opus-4-7`.
The bridge inherits MCP plumbing from `.claude/settings.local.json`, so the
runtime can call MCP tools directly. Every channel (Telegram, WhatsApp,
Instagram, website chat, world events) routes through one
`Orchestrator` that adds session history, brand-voice lint, and an
audit-log entry. Full diagram in `ARCHITECTURE.md`.

## Run it from a clean clone

```bash
git clone <this-repo> hackaton && cd hackaton

# 1. Python deps
uv sync

# 2. tokens (Telegram bot + SBC team token; both required)
cp config/.env.example .env
# fill TELEGRAM_BOT_TOKEN and SBC_TEAM_TOKEN

# 3. quality gate (clean)
uv run ruff check src tests scripts examples
uv run mypy src
uv run pytest -q                 # 103 tests, ~5s

# 4. web build (offline-safe; uses fallback catalog if backend is down)
cd web && npm install && npm run build && cd ..

# 5. five-minute end-to-end demo against the live MCP
./scripts/demo.sh
```

The demo:

1. Starts the FastAPI storefront API on `:8000`.
2. Runs the marketing loop end-to-end (2 campaigns + 6 leads + adjust + report).
3. Replies to every seeded Google Business review.
4. Generates 3 Instagram post drafts and queues them for `/drafts` approval.
5. Drives the world-engine scenario with `WorldPoller` + periodic `world_advance_time`.
6. Self-grades via the five `evaluator_score_*` tools and writes
   `data/team_report.json`.

The full operator runbook (manual / interactive flows, Telegram-side
walkthroughs, troubleshooting) is in **`docs/DEMO.md`**.

## Documentation

| File | What's in it |
|---|---|
| `ARCHITECTURE.md` | Two-Claude pattern, MCP routing, owner controls, channel adapters, POS + kitchen handoff, marketing loop, agent-friendliness surfaces, storage model, layout |
| `docs/PLAN.md` | Live execution plan + the locked architectural decisions (do not relitigate) |
| `docs/specs.md` | Acceptance criteria for all 6 workflows (60 ACs, 24 edge cases, 12 cross-cutting brand rules) — produced by `brief-analyst` at H+0 |
| `docs/mcp_inventory.md` | All 55 MCP tools across 8 families with schemas + sample success / failure shapes — produced by `mcp-recon` at H+0 |
| `docs/CONTRACTS.md` | Web ↔ backend API contract (the storefront and the FastAPI app build to this) |
| `docs/MARKETING_PLAN.md` | $500/month plan with margin / AOV / conversion math + Sugar Land context (executable form: `scripts/seed_marketing.py`) |
| `docs/DEMO.md` | Operator runbook from clean clone to artefacts |
| `docs/critic_report.md` | Phase 4 critic scorecard (4 rubrics: code review, agent friendliness, operator UX, business analyst) |
| `docs/decisions.md` | ADR log |
| `HCU_BRANDBOOK.md` | The brand book — voice, palette, hard rules; the runtime persona is derived from this |
| `HACKATHON_BRIEF.md` | The unsealed brief, verbatim |
| `agent/README.md` | Why the persona is split into 4 files and how the composer wires them together |

## What's deliberately out of scope

Per `ARCHITECTURE.md` §11: real Square / Meta / Google Ads credentials,
multi-language copy, multi-tenant auth, LLM fine-tuning, microservices.
Single process, single host, single tenant — that's the brief.

## License & IP

Per the hackathon rules, submitted IP transfers to Steppe Business Club;
this team retains a portfolio license. The repo remains public after the
event.
