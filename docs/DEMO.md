# Demo — running HappyCake AI from a clean clone

This page is the operator's runbook for the submission. A judge or
reviewer should be able to clone the repo, follow it from top to bottom,
and have the system exercising every scoring dimension within a few
minutes. Every step here is also automatable via `scripts/demo.sh`.

## 0. Setup (one-time)

```bash
git clone <this-repo>
cd hackaton
uv sync                                # installs Python deps
uv run python -c "import src.bot.app"  # smoke-import
cp config/.env.example .env            # then fill the two required tokens
```

`.env` must have:

| Var | Where to get it |
|---|---|
| `TELEGRAM_BOT_TOKEN` | The bot token for `@dust2ai_steppehackaton_owner_bot` (rotate via @BotFather if compromised) |
| `SBC_TEAM_TOKEN` | The hackathon team token (already configured in `.claude/settings.local.json` for Claude Code; mirror it into `.env` so the Python client picks it up) |

Optional but recommended: `OWNER_CHAT_ID` (your Telegram chat id; the
bot also captures this on the first `/start`).

The runtime persona requires the **`claude` CLI** (Claude Code) on
PATH. The bridge subprocesses `claude -p --system-prompt …` for every
inbound message; without the CLI, replies become `(no response)` but
the audit + scoring path still works.

## 1. Web build (one-time)

```bash
cd web
npm install
npm run build
cd ..
```

`npm run build` exits 0 with 8 routes generated under `web/dist/` even
when the backend is offline (a fallback catalog is baked into the
static build). At runtime the chat widget and `/api/catalog` read the
live MCP through the FastAPI backend.

## 2. One-port public demo (recommended)

```bash
./scripts/start_demo.sh
```

The script builds `web/` with relative API URLs, starts FastAPI on
`:8000` (the storefront is mounted as a static catch-all), opens an
ngrok tunnel, and prints the **public HTTPS URL**. Open the URL in a
browser — the storefront and the chat widget post back to the same
origin (no separate Astro server, no CORS gymnastics). Press Ctrl-C
to stop both processes.

## 3. Five-minute scoring demo (automated)

```bash
./scripts/demo.sh
```

The script:

1. Starts `src.webhooks.app` on `http://127.0.0.1:8000` in the
   background and waits for `/health`.
2. Drives the marketing loop end-to-end (`scripts/seed_marketing.py`)
   — creates 2 campaigns from `docs/MARKETING_PLAN.md`, launches them,
   generates leads, routes each lead with a reason, files a final
   `marketing_report_to_owner`.
3. Replies to every seeded Google Business review
   (`scripts/seed_review_replies.py`) — the runtime persona writes a
   brand-voice reply per brandbook §6 and posts it via
   `gb_simulate_reply`.
4. Generates three Instagram post drafts
   (`scripts/seed_drafts.py`) — one per brandbook content group
   (Product / Audience / Company), schedules each via
   `instagram_schedule_post`, and persists them locally so the
   Telegram `/drafts` command can list and approve them.
5. Drives the world engine (`scripts/run_scenario.py`) with
   `world_start_scenario("launch-day-revenue-engine")` and the
   `WorldPoller`, periodically calling `world_advance_time` so the
   480-min scenario fits inside a real-time minute.
6. Self-grades via the five `evaluator_score_*` tools and writes the
   final `evaluator_generate_team_report` to `data/team_report.json`.

Artefacts:

- `data/scorecard_<timestamp>.json` — per-run scorecard from
  `run_scenario.py` (per-dimension scores + evidence).
- `data/team_report.json` — the final combined report we'd submit
  alongside the repo URL.
- `data/uvicorn.log` — backend logs from the demo run.
- `data/state.db` — SQLite with sessions, audit log, drafts, leads.

## 3. Manual / interactive demo

In separate terminals:

| Terminal | Command | What it does |
|---|---|---|
| 1 | `uv run uvicorn src.webhooks.app:app --reload --port 8000` | Storefront API + chat backend |
| 2 | `uv run python -m src.bot.app` | Telegram bot polling (owner-side) |
| 3 | `cd web && npm run dev` | Astro dev server on `http://localhost:4321` |
| 4 | `./scripts/start_tunnel.sh` | ngrok public URL (optional, for inbound Meta-shaped webhooks) |

Then from another terminal you can drive any of the seed scripts
individually:

```bash
uv run python scripts/seed_marketing.py        # exercise marketing loop
uv run python scripts/seed_review_replies.py   # reply to GB reviews
uv run python scripts/seed_drafts.py           # queue IG drafts
uv run python scripts/run_scenario.py          # world engine end-to-end
```

In Telegram:

| Command | Demonstrates |
|---|---|
| `/start` | First-time owner identity capture (writes `chat_id` to `owner_identity`) |
| `/help` | Command listing |
| `/dashboard` | POS, kitchen, evaluator summaries pulled live from MCP |
| `/budget` | Marketing budget + recent website leads |
| `/drafts` | Lists pending drafts with **Approve / Edit / Reject** inline keyboard. Approving an Instagram draft drives `instagram_approve_post` + `instagram_publish_post`. |
| free text | Bridges through `claude -p` with the runtime persona; the orchestrator runs the brand-voice linter on the reply. |

In the browser at `http://localhost:4321`:

- `/` — homepage with hero + featured cakes from `/api/catalog`
- `/cake/<slug>` — product page with JSON-LD Product + Offer (covers
  w2.ac1 — agent-friendly Schema.org)
- `/policies` — pickup, delivery, lead times, refunds, allergens, halal
- `/order?slug=…&utm_source=meta&utm_campaign=mothers_day_2026` — lead
  form; submission posts `/api/lead` and triggers
  `marketing_report_to_owner`
- `/sitemap.xml`, `/robots.txt`, `/catalog.json` — agent-friendly
  surfaces
- The floating chat widget — POSTs `/api/chat`, which goes through the
  orchestrator → `claude -p` → MCP

## 4. What each evaluator dimension is exercised by

| Evaluator dimension | Where it fires |
|---|---|
| `evaluator_score_marketing_loop` | `scripts/seed_marketing.py` runs the full plan→launch→leads→route→adjust→report cycle |
| `evaluator_score_pos_kitchen_flow` | `scripts/run_scenario.py` events: when the runtime persona accepts an order in WhatsApp / IG, it calls `square_create_order` + `kitchen_create_ticket` via MCP |
| `evaluator_score_channel_response` | WhatsApp + Instagram + Google Business all see traffic — WA / IG via the `WorldPoller` dispatchers, GB via `seed_review_replies.py` |
| `evaluator_score_world_scenario` | `run_scenario.py` calls `world_start_scenario` and drains events with `WorldPoller` + `world_advance_time` |
| Functional Tester (customer scenarios) | The on-site widget, world events, and Telegram free-text all route through the orchestrator and never hardcode answers |
| Agent-friendliness auditor | `web/` exposes JSON-LD per product, `/catalog.json`, `/policies` JSON, `/sitemap.xml`, predictable URLs |
| On-site assistant evaluator | The chat widget at `web/public/chat-widget.js` posts to `/api/chat`; replies are MCP-grounded |
| Operator UX (Telegram) | `/dashboard`, `/budget`, `/drafts` (with inline keyboard), `/help`, `/cancel`, `/restart` — all replies acknowledge within ~2 s |
| Code reviewer | `git log` shows scoped conventional commits per phase; `pyproject.toml` runs ruff + mypy --strict + pytest at every commit (pre-commit hook) |
| Business analyst | `docs/MARKETING_PLAN.md` carries the $500 reasoning with margin/AOV/conversion math and Sugar Land context |

## 5. Reset between runs

The simulator state is per-team-token. Re-running `world_start_scenario`
resets the world timeline. To reset local state:

```bash
rm -f data/state.db data/scorecard_*.json data/team_report.json
```

The migration runner re-creates the schema on the next start.

## 6. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `claude CLI not found` from the bridge | `claude` not on PATH | Install Claude Code; verify with `which claude` |
| `auth failed (401)` from MCP | bad / missing `SBC_TEAM_TOKEN` | Re-fill `.env` from your team page |
| `npm run build` mentions sitemap and crashes | stale `@astrojs/sitemap` install | We replaced the integration with `web/src/pages/sitemap.xml.ts`; run `npm uninstall @astrojs/sitemap` if present |
| Telegram `/dashboard` says "_unable to fetch_" | MCP unreachable | Check `data/uvicorn.log` and `SBC_MCP_URL` |
| `voice_warnings` field non-empty in `/api/chat` response | runtime reply tripped a brand rule (logged) | Inspect `data/state.db` audit log; refine the persona under `agent/` |
