# HappyCake AI — Project description

> An AI-assisted sales and operations system for **HappyCake US** (Sugar Land, TX —
> a family cake business). Submission for the Steppe Business Club hackathon
> *Agentic AI for Real Business* (May 9–10, 2026).

This file is the entry point for anyone reading the repo — judges, reviewers, future
maintainers, and the model itself when it's invoked from this directory. It says
*what* this is and *how it works at a glance*. The execution plan and active task list
live in `docs/PLAN.md`. The runtime persona (the system prompt the customer-facing
Claude actually runs with) lives in `agent/`. Brand voice and rules of the business
live in `HCU_BRANDBOOK.md`.

## What this system does

HappyCake is a small, real cake business with a website (`happycake.us`), Instagram,
WhatsApp, Google Business profile, walk-in counter, and a Square POS. This project
wraps a single AI agent around all of those surfaces so that:

| Outcome | What the agent does |
|---|---|
| **Website + storefront** | Hosts the catalog, custom-order intent capture, and an on-page chat that grounds every answer in MCP tool results. |
| **Agent-friendly site** | Exposes Schema.org JSON-LD, predictable URLs, and a machine-readable `/catalog.json` so other agents can shop here. |
| **On-site assistant** | The chat widget answers product, policy, and timing questions in HappyCake's voice and escalates anything custom to the owner. |
| **WhatsApp** | Replies to inbound customer messages within the brand voice, captures orders, places them in the POS, and notifies the kitchen. |
| **Instagram** | Replies to DMs and comments, drafts feed posts, queues them for owner approval before publishing. |
| **Marketing** | Plans and runs a $500 monthly campaign aimed at $5,000 attributable revenue, with attribution back to the POS. |

## Architecture: two Claudes, by design

| Layer | Identity | Where it lives | How it's invoked |
|---|---|---|---|
| **Dev Claude** | Project planner / coder / reviewer | This `CLAUDE.md` + `.claude/agents/*.md` (planner, coder, tester, brief-analyst, mcp-recon, critic) + `docs/PLAN.md` | Developer runs Claude Code in this directory |
| **Runtime Claude** | The HappyCake assistant — brand voice, MCP tool user, owner-escalator | `agent/{SOUL,RULES,TOOLS,EXAMPLES}.md`, composed by `src/agents/system_prompt.py` | `src/agents/claude_bridge.py` shells out to `claude -p --system-prompt …` with `ANTHROPIC_MODEL=claude-opus-4-7` |

The bridge passes `--system-prompt` so the runtime persona is **deterministic** — it
doesn't drift with edits to this file or the project context. The runtime model is
pinned to **Opus 4.7** as the brief mandates. The runtime accesses MCP tools through
the same `.claude/settings.local.json` configuration that Dev Claude uses.

## Stack

- **Python 3.12**, `uv` for env + deps
- **`aiogram` 3.x** — Telegram bot (owner-side approvals + dashboards), polling
- **`fastapi` + `uvicorn`** — inbound webhooks for WhatsApp, Instagram, and the
  on-site `/api/chat` endpoint
- **`mcp` Python client** — for the organizer-hosted `happycake` MCP server
- **`sqlite` + `aiosqlite`** — sessions, FSM state, audit log, drafts queue
- **`ruff`** (lint+format), **`mypy`** (strict types), **`pytest`** + `pytest-asyncio`
- **`ngrok`** — public tunnel for inbound webhooks
- **`claude` CLI (Claude Code)** — runtime LLM. **Not** the Anthropic SDK — the brief
  forbids "other LLM providers for the core runtime", and `claude -p` is the explicitly
  allowed runtime path.

The website (separate top-level `web/` Astro project, added in Phase 2) ships its own
package list.

## Repository layout

```
agent/        Runtime persona — composed system prompt for `claude -p`
  SOUL.md     Identity, voice, values
  RULES.md    Hard + soft rules, escalation triggers
  TOOLS.md    MCP tool catalog with when-to-use guidance
  EXAMPLES.md Reference posts and reply templates
src/          Application code
  agents/     system_prompt.py (composer), claude_bridge.py (subprocess shim)
  bot/        aiogram Telegram handlers, FSM, middleware
  webhooks/   FastAPI inbound (WhatsApp, Instagram, on-site /api/chat)
  mcp/        MCP client wrapper + per-server adapters
  workflows/  One module per business workflow (Phase 2+)
  storage/    SQLite session store, drafts table, audit log
  core/       Config, logging, errors, idempotency, retry
tests/        Tests
  scenarios/  YAML acceptance criteria → test cases
  unit/       Module-level unit tests
  integration/ End-to-end through bot + MCP
docs/         Project documentation
  PLAN.md     Live execution plan and locked decisions (always current)
  specs.md    Acceptance criteria per workflow (from brief-analyst)
  mcp_inventory.md  Live MCP tool catalog with schemas (from mcp-recon)
  decisions.md  Short ADR log
  critic_report.md  Latest critic scorecard
config/       env templates, MCP config
scripts/      Tunnel start, scenario runner, etc.
examples/     Reference snippets, NOT production code
HACKATHON_BRIEF.md  The unsealed event brief (verbatim)
HCU_BRANDBOOK.md    Brand voice, rules, references (the runtime's source of truth)
assets/             Brand assets (logos, photography, palette references)
```

`_workfiles/` is gitignored — it holds session-handover docs and reconnaissance
scratchpads that don't belong in the submission repo.

## Hard project rules (apply at every layer)

- **Never hardcode answers to test scenarios.** Every customer-visible answer must come
  from an MCP tool call or sandbox data at runtime. The Functional Tester evaluator
  detects hardcoding (−10 pts + public note).
- **No fabricated data.** If a tool returns nothing, say so; do not invent.
- **No secrets in repo.** No `.env`, no API keys, no credentials. `.env.example` only.
- **Files under 500 lines.** Split before that.
- **Public APIs are typed.** `mypy --strict` is the bar.
- **Validate input at every boundary** — Telegram handler, webhook, MCP wrapper.
- **Idempotency for side effects.** Use idempotency keys for any tool call that writes;
  safe to retry.

## How to run it

Setup:

```bash
uv sync                                        # install deps
cp config/.env.example .env                    # fill TELEGRAM_BOT_TOKEN, SBC_TEAM_TOKEN
uv run ruff check src tests scripts examples   # lint
uv run mypy src                                # types (strict)
uv run pytest -q                               # tests
```

Bring up the system:

```bash
# In one terminal — public tunnel for inbound webhooks
./scripts/start_tunnel.sh

# In another — Telegram bot polling
uv run python -m src.bot.app

# In a third — FastAPI for /api/chat + WhatsApp/Instagram webhooks
uv run uvicorn src.webhooks.app:app --reload
```

The runtime model needs `claude` (Claude Code CLI) on `PATH`. The bridge calls
`claude -p --system-prompt "$(composed)"` with `ANTHROPIC_MODEL=claude-opus-4-7`.

## Submission deliverables (per brief §8)

- Public GitHub repo with final commit before May 10, 10:00 CT
- `README.md` with clean clone setup
- `ARCHITECTURE.md` (agents, routing, owner controls, MCP usage)
- `.env.example` with placeholders only
- Website / storefront instructions and deploy notes
- Agent-friendly notes (catalog/policies readable, ordering path autonomous)
- On-site assistant test script (`docs/DEMO.md` or scripts)
- Marketing/channel/POS/kitchen scenarios documented with expected behavior
- Evidence of tests, smoke checks, scripted demos
- Real-adapter path documented (without exposing credentials)

## Working in this repo (developer notes)

These rules apply to anyone editing this codebase. They are *not* the runtime persona's
rules — those live in `agent/RULES.md`.

### File ownership (avoid stomping)

- **Planner** writes only TaskList + `docs/decisions.md` + `docs/PLAN.md`
- **Coder** writes `src/**`, `pyproject.toml`, `config/**` (no test code)
- **Tester** writes `tests/**`, `scripts/run_scenarios.py`
- **Brief Analyst** writes `docs/specs.md` (one-shot at H0)
- **MCP Recon** writes `docs/mcp_inventory.md` (one-shot at H0–H1)
- **Critic** is **read-only** on `src/`, `tests/`, `agent/`; writes only
  `docs/critic_report.md`

### Tool-authoring conventions (Agent-Friendliness scoring)

When defining new tools or shaping schemas:

1. **Verb-noun names**, lowercase snake_case (`lookup_customer_by_phone`).
2. **Docstring is the system prompt for that tool.** Include: one-line purpose, when
   to use it, when NOT to use it, what it returns, failure modes.
3. **Return structured JSON-serializable dicts.** Always include
   `status: "ok" | "not_found" | "error"`.
4. **Idempotent writes.** Accept `idempotency_key`. Same key → same result.
5. **Surface "I don't know" cleanly.** Never raise on missing data; return
   `{"status": "not_found", ...}`.

### Telegram bot conventions (Operator UX scoring)

- Reply within 2s of an inbound message (ack first, work async).
- Long-running actions send a "working on it…" + final result.
- Inline keyboards for any choice with ≤6 options; free text otherwise.
- Errors are human-readable, never raw stack traces.
- `/start`, `/help`, `/cancel`, `/restart` always work, in any state.
- Persist FSM state in SQLite, not memory — survive restarts.

### Concurrency rules

- Spawn multiple subagents in **one** message when independent (different file paths).
- Sequential when one depends on another's output (Brief Analyst → Tester).
- Never spawn two agents that both write to `src/` at once.
- Maximum two coder subagents in parallel.

### Cost discipline

The brief disallows the Anthropic SDK for the runtime. The dev environment uses Claude
Code on the user's Max subscription; runtime LLM access is `claude -p` against the
same subscription. There is no Anthropic API spend in production.

### Commit hygiene

Conventional commits, scoped: `feat(bot): add /restart handler`,
`test(scenarios): cover edge case 4.2`. Small commits, frequent. The Code Reviewer
evaluator reads `git log`.

### What's deliberately out of scope

- Microservices, k8s, multi-region — single process, single host.
- Auth / multi-tenant — sandbox is single-tenant.
- Custom UI beyond Telegram + a small on-site widget.
- Anything that doesn't move one of the seven evaluator scoreboards.
