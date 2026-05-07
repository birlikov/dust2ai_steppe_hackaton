# dust2ai — Steppe Business Club Hackathon

> 24h agentic-AI submission for the Steppe Business Club hackathon (May 9–10, 2026).
> The Business Analyst evaluator (10 pts) reads this file. The placeholder sections
> below are filled at H+22 once the four workflows have landed.

## Problem

_TBD at H+22 — the Business Analyst Critic fills this from `docs/specs.md` and
the unsealed brief at `docs/brief.md`. State the actual operational gap the
business has today, in 3 sentences max._

## Solution

_TBD — one paragraph mapping our four agentic workflows to the problem above._

| Workflow | Problem it solves | Channel | Key tools used |
|---|---|---|---|
| 1. _name_ | … | telegram / wa / ig | … |
| 2. _name_ | … | … | … |
| 3. _name_ | … | … | … |
| 4. _name_ | … | … | … |

## How it works (architecture)

```
                  ┌────────────────────┐
   Telegram  ────▶│  aiogram bot       │──┐
                  │  (polling)         │  │
                  └────────────────────┘  │
                                          ▼
   WhatsApp  ────▶┌────────────────────┐ ┌──────────────────┐
   Instagram ────▶│  FastAPI webhook   │▶│  Anthropic agent │
                  │  (signed POST)     │ │  loop (tool-use) │
                  └────────────────────┘ └────────┬─────────┘
                          ▲                       │
                          │                       ▼
                    ngrok tunnel         ┌──────────────────┐
                                         │  MCP registry    │
                                         │  (org + local)   │
                                         └────────┬─────────┘
                                                  │
                                          ┌───────┴────────┐
                                          ▼                ▼
                                   Organizer MCP    SQLite (sessions,
                                   servers + data   FSM, idempotency,
                                                    audit log)
```

- Tier-routed model selection: Haiku by default, promote to Sonnet/Opus on observed gaps
- Prompt + tool-definition caching to keep cost down across the 24h + 6h eval window
- All mutating tool calls accept idempotency keys
- Full audit log of every inbound, tool call, tool result, outbound

## User journey

### Customer (WhatsApp / Instagram)
_TBD — one walk-through per workflow, from first message to satisfied outcome._

### Business owner (Telegram)
_TBD — daily-driver flow: morning summary, exception handling, end-of-day._

## Value (ROI)

_TBD — quantified per workflow at H+22:_

- _Workflow 1_: ~X hours/week saved, Y errors avoided per Z customers
- _Workflow 2_: …
- _Workflow 3_: …
- _Workflow 4_: …

## Limitations

_TBD — honest list of what this 24h build does NOT do, e.g. multi-language,
multi-tenant, real Meta integration (organizer-bridged), historical analytics
beyond audit log, etc._

## Run it

```bash
# 1. install
uv sync --dev
cp config/.env.example .env  # then fill TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY, etc.

# 2. tests
uv run ruff check src tests
uv run mypy src
uv run pytest -q

# 3. run the bot (Telegram, polling)
uv run python -m src.bot.app

# 4. run the webhook receiver behind ngrok
./scripts/start_tunnel.sh                # default port 8000

# 5. run the scenario harness
uv run python scripts/run_scenarios.py tests/scenarios/
```

## Repository layout

| Path | What lives there |
|---|---|
| `CLAUDE.md` | Project conventions for Claude Code + AI judges |
| `.claude/agents/` | Subagent definitions (planner, coder, tester, critic, …) |
| `src/agents/` | Anthropic tool-use loop, model tiering |
| `src/bot/` | aiogram Telegram bot |
| `src/webhooks/` | FastAPI inbound + signature verification |
| `src/mcp/` | MCP server registry + namespaced tool dispatch |
| `src/storage/` | SQLite sessions, FSM, idempotency, audit log |
| `src/scenarios/` | Acceptance-test runner |
| `src/workflows/` | One module per business workflow (filled at H+0) |
| `tests/` | Unit + scenario tests |
| `docs/` | brief, specs, mcp inventory, decisions, critic report |
| `config/` | `.env.example`, `mcp.json`, SQL migrations |

## License & IP

Per the hackathon rules, submitted IP transfers to Steppe Business Club; this
team retains a portfolio license. Repo remains public post-event.
