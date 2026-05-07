# Project: Steppe Business Club Hackathon — Agentic AI for Real Business

24-hour hackathon (May 9 10:00 CT → May 10 09:30 CT). Solo team. Stack: Python.
We build agentic workflows for a real business using Claude Code CLI + Opus 4.7. Owner interacts via Telegram bot(s); customer messages arrive via WhatsApp/Instagram webhooks. Organizers provide hosted MCP servers and anonymized data at kickoff.

## Hard rules (never violate)

- **Never hardcode answers to test scenarios.** Every customer-visible answer must be derived from MCP tool calls or sandbox data at runtime. The Functional Tester evaluator detects hardcoding (−10 pts + public note).
- **No fabricated data.** If a tool returns nothing, say so; do not invent a response.
- **No secrets in repo.** No `.env`, no API keys, no credentials. `.env.example` only.
- **Files under 500 lines.** Split before that.
- **Public APIs are typed.** Use `typing` everywhere a function crosses a module boundary.
- **Validate input at every boundary** (Telegram handler, webhook, MCP tool wrapper).
- **Idempotency for side effects.** Use idempotency keys for any tool call that writes; safe to retry.

## Stack

- Python 3.12, `uv` for env + deps
- `aiogram` 3.x for Telegram bot (async, FSM)
- `fastapi` + `uvicorn` for inbound webhooks (WhatsApp/Instagram-shaped)
- `anthropic` SDK (raw, with API key) for the bot's runtime LLM calls — prompt caching + tool-use loop
- `mcp` Python client for organizer-hosted MCP servers, exposed to the agent loop as Anthropic tools
- `sqlite` for session/state; `sqlite-vec` or local sentence-transformers for retrieval if needed
- `ruff` (lint+format), `mypy` (types), `pytest` + `pytest-asyncio` (tests)
- `ngrok` tunnel for public URL

## Runtime model & cost discipline

The bot calls the Anthropic API directly with our API key. The Max subscription
is for our Claude Code **dev environment** (us building this), not the bot's
runtime. Organizers do not reimburse API credits, so cost is part of the design.

### Model tiering — default cheap, promote on observed gaps

| Tier | Model ID | Use for |
|---|---|---|
| Cheap | `claude-haiku-4-5` | Intent routing, classification, tool-result formatting, FSM transitions, simple Q&A |
| Default | `claude-sonnet-4-6` | Multi-turn conversation, workflow execution where Haiku gets fuzzy |
| Heavy | `claude-opus-4-7` | Only when reasoning depth genuinely matters — gnarly business logic, ambiguous edge cases |

Start every workflow on Haiku. Promote to Sonnet when a scenario fails on Haiku
and the failure is reasoning-quality, not prompt-quality. Reserve Opus for the
small fraction of turns that need it.

### Caching

- System prompts and tool definitions: `cache_control: {"type": "ephemeral"}`
- Long sandbox docs (FAQs, pricing, brand voice): cache once per workflow boot
- Conversation history: cache the prefix that doesn't change turn-to-turn

### Test cost containment

- **Unit tests** mock `AnthropicClient` at the SDK boundary — no real LLM calls
- **Scenario tests** use the real LLM but on the cheapest model that passes
- Run the full scenario suite **before pushing**, not on every commit
- Local sandbox / MCP calls are free — exercise those without restraint

## Layout & ownership

```
src/        Coder owns. Application code only.
  agents/   Anthropic SDK glue, tool definitions, system prompts
  bot/      aiogram Telegram handlers, FSM, middleware
  webhooks/ FastAPI inbound (WhatsApp/Instagram)
  mcp/      MCP client wrapper + per-server adapters
  workflows/ One module per business workflow (workflow_1.py, ...)
  storage/  SQLite session store, repository pattern
  core/     Config, logging, errors, idempotency, retry
tests/      Tester owns. pytest scenarios, integration runs.
  scenarios/  YAML acceptance criteria → test cases
  unit/       module-level unit tests
  integration/ end-to-end through bot + MCP
docs/       Brief Analyst + Critic write here.
  brief.md           verbatim event brief (paste at H0)
  specs.md           acceptance criteria YAML extracted from brief
  mcp_inventory.md   MCP Recon output: servers, tools, schemas
  decisions.md       short ADR log (only real architectural calls)
  critic_report.md   Critic latest scorecard (overwritten per pass)
config/     env templates (.env.example), bot menu schema, prompts
scripts/    one-shot utilities (tunnel start, replay session, scenario runner)
examples/   reference snippets, NOT production code
```

## Agent file ownership (avoid stomping)

- **Planner** writes only TaskList + `docs/decisions.md`
- **Coder** writes `src/**`, `pyproject.toml`, `config/**` (no test code)
- **Tester** writes `tests/**`, `scripts/run_scenarios.py`
- **Brief Analyst** writes `docs/specs.md` (one-shot at H0)
- **MCP Recon** writes `docs/mcp_inventory.md` (one-shot at H0–H1)
- **Critic** is **read-only** on `src/` and `tests/`; writes only `docs/critic_report.md`

## Tool authoring conventions (Agent-Friendliness scoring)

When defining tools for the LLM:

1. **Verb-noun names**, lowercase snake_case: `lookup_customer_by_phone`, not `customer_lookup` or `getCustomer`.
2. **Docstring is the system prompt for that tool.** Include: one-line purpose, when to use it, when NOT to use it, what it returns, failure modes.
3. **Return structured JSON-serializable dicts.** Never raw strings for data. Always include `status: "ok" | "not_found" | "error"`.
4. **Idempotent writes.** Accept `idempotency_key`. Same key → same result.
5. **Surface "I don't know" cleanly.** Tools never raise on missing data; return `{"status": "not_found", ...}`.

## Telegram bot conventions (Operator UX scoring)

- Reply within 2s of an inbound message (ack first, work async)
- Every long-running action sends a "working on it…" + final result
- Inline keyboards for any choice with ≤6 options; free text otherwise
- Errors are human-readable, never raw stack traces
- `/help`, `/cancel`, `/restart` always work, in any state
- Persist FSM state in SQLite, not memory — survive restarts

## Build & test

```bash
uv sync                          # install
uv run ruff check src tests      # lint
uv run mypy src                  # types
uv run pytest -q                 # tests
uv run python scripts/run_scenarios.py   # acceptance scenarios
```

CI on every push runs ruff + mypy + pytest. Red CI = nothing else matters.

## Commit hygiene

Conventional commits, scoped: `feat(bot): add /restart handler`, `test(scenarios): cover edge case 4.2`. Small commits, frequent. The Code Reviewer evaluator reads git log.

## Concurrency rules

- Spawn multiple subagents in **one** message when independent (different file paths)
- Sequential when one depends on another's output (Brief Analyst → Tester writing scenarios)
- Never spawn two agents that both write to `src/` at once

## What's deliberately out of scope

- Microservices, k8s, multi-region — single process, single host, that's the brief
- Auth/multi-tenant — sandbox is single-tenant
- Custom UI beyond Telegram + minimum on-site widget if required
- LLM fine-tuning — Opus 4.7 + good prompts + tools is the brief
