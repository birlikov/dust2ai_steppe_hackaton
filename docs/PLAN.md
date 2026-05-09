# HappyCake AI — Hackathon Execution Plan

> **Live plan, single source of truth.** Updated on every commit. Any contributor or future session reads this file first, then `_workfiles/HANDOFF.md` for internal-only context.

## Project goal

Build a working AI-assisted sales and operations system for **HappyCake US** (Sugar Land, TX cake business) for the Steppe Business Club hackathon, deadline **May 10, 2026 10:00 CT**. Submission is a public Git repo plus a live demo runnable from a fresh clone.

## Architecture: two Claudes, by design

| Layer | Identity | Where defined | Invoked by |
|---|---|---|---|
| **Dev Claude** | Project planner / coder / reviewer | Root `CLAUDE.md` (project description, audience-neutral) + `.claude/agents/*.md` (planner, coder, tester, brief-analyst, mcp-recon, critic) | Developer in chat sessions; `Agent` tool spawns |
| **Runtime Claude (HappyCake assistant)** | Customer-facing brand voice, MCP tool user, owner-escalator | `agent/{SOUL,RULES,TOOLS,EXAMPLES}.md` composed by `src/agents/system_prompt.py` | `src/agents/claude_bridge.py` shells out to `claude -p --system-prompt …` (Opus 4.7 via Max sub) |

The bridge passes `--system-prompt` so the runtime persona is **deterministic**, regardless of inherited project context.

## Six outcomes targeted (from brief §3)

| # | Outcome | Narrow but real definition |
|---|---|---|
| 1 | Website / storefront | Astro + Tailwind site at happycake.us-style domain: hero, catalog, product pages, policies, custom-order intent. Brand-styled, mobile-first. |
| 2 | Agent-friendly site | Schema.org Product + Offer JSON-LD, predictable URLs, machine-readable `/catalog.json`, robots-friendly. |
| 3 | On-site assistant | Chat widget posting to `/api/chat`; answers via runtime Claude + MCP catalog/policies; escalates to owner Telegram for complex/custom orders. |
| 4 | WhatsApp | `world_next_event` polling delivers simulated WA messages → runtime Claude → reply via outbound MCP; brand voice. |
| 5 | Instagram | Same handler family as WA; channel-routed; DM order capture; comment replies; post drafts go to Telegram approval queue. |
| 6 | Marketing $500 plan | `/budget` Telegram command + `docs/MARKETING_PLAN.md` + at least one real campaign created via `marketing_create_campaign` MCP tool. |

## Locked decisions (with rationale)

| Decision | Rationale |
|---|---|
| Runtime is `claude -p` headless, not the Anthropic SDK | Brief explicitly allows `claude -p`, disallows Agent SDK and "other LLM providers for the core runtime." |
| Opus 4.7 pinned via env (`ANTHROPIC_MODEL=claude-opus-4-7`) | Brief mandates it; belt-and-suspenders pin removes ambiguity. |
| `--system-prompt` flag passes the composed runtime persona | Replaces Claude Code's default system prompt, so persona doesn't drift with CLAUDE.md edits. |
| Persona is 4 small files (SOUL, RULES, TOOLS, EXAMPLES) under `agent/` | Each file has one job; editable independently; reviewable; signals architectural rigor. |
| Conversation history pattern A: prepend formatted history to each prompt | Always works; transparent; fits existing audit log + `sessions.state`. Cap N=12 turns. |
| World engine is the integration test backbone (`world_start_scenario` / `world_next_event`) | Brief says judges drive the same compressed business day; we self-grade via `evaluator_score_world_scenario`. |
| Scenario YAML harness kept for unit-style smoke checks (no LLM, no MCP) | Fast pre-commit gate; complementary to world engine. |
| At most 2 coder subagents in parallel; never 3 | 3-way merge conflicts and context fragmentation outweigh throughput gain at our scale. |
| Approval flow is a Telegram inline-keyboard subsystem with a `drafts` SQLite table | Brandbook §7 mandates it; persistence survives bot restart. |
| No fabrication: every answer about price/flavor/hours/policy/availability is preceded by an MCP call | Brandbook §7 hard rule + brief evaluator checks for evidence in `mcp_audit_log`. |
| Anthropic API key removed from `.env` and `pyproject.toml`; `anthropic` + `respx` deps dropped | User direction: avoid signaling we used the SDK; brief reads strict on "other LLM providers." |
| `ngrok` for the public tunnel | User preference; brief allows ngrok or Cloudflare. |
| Polling for the Telegram bot (no webhook) | Simpler, fewer moving parts; bot stays alive across tunnel restarts. |
| Repo cleanliness: saved hackathon HTML pages live in gitignored `_workfiles/`; brand assets under `assets/brand/`; brandbook + brief at root | Submission readability; judges see a clean repo. |

## Twelve gap-fixes (locked)

1. **Delete Anthropic SDK stack.** Remove `src/agents/loop.py`, `src/agents/models.py`, `tests/unit/test_agent_loop.py`, `tests/integration/test_dry_run.py`. Drop `anthropic` + `respx` from deps. Replace with `src/agents/claude_bridge.py` + `tests/unit/test_claude_bridge.py` (mock subprocess).
2. **Approval queue.** New `drafts` SQLite table + `src/bot/drafts.py`. Inline keyboard Approve / Edit / Reject. Survives restart.
3. **Kitchen capacity precondition.** Hard rule in `agent/RULES.md`: every availability/timing answer requires a prior `kitchen_get_production_summary` call; cite it in the reply for evidence.
4. **Marketing attribution loop.** Landing pages parse `?utm_source=` and `?utm_campaign=`; lead form persists attribution; on submit `marketing_report_to_owner` closes the loop.
5. **Owner chat ID capture.** First `/start` writes `is_owner=true` to `sessions.state`; fallback `OWNER_CHAT_ID` env var.
6. **MCP retry/backoff.** Tiny `src/core/retry.py`: 3 attempts, exponential, jitter. Used by world poller + direct MCP HTTP calls.
7. **Brand-voice linter.** `src/core/voice.py`: catches "Happy Cake", banned adjectives, emoji-chains, missing closing pattern. Runs on every outbound payload.
8. **Demo evidence.** `scripts/demo.sh` + `docs/DEMO.md`: starts system, runs `world_start_scenario "first_day"`, drives happy-path through every channel, calls `evaluator_generate_team_report`, saves transcript + scorecard.
9. **Two-layer testing.** Keep YAML harness for unit smoke; world engine for integration.
10. **Handover artifact.** This file (`docs/PLAN.md`) committed; `_workfiles/HANDOFF.md` gitignored for internal continuity.
11. **Subfolder separation.** `agent/` folder for runtime persona docs (SOUL, RULES, TOOLS, EXAMPLES, README). Rewrite root `CLAUDE.md` as project description; move dev-team operational rules to a small "## Working in this repo" appendix or `docs/DEVELOPMENT.md`.
12. **Composer + bridge.** `src/agents/system_prompt.py` reads `agent/*.md` in deterministic order, composes the system prompt. `claude_bridge.py` calls `claude -p --system-prompt … --append-history-flag …` with `ANTHROPIC_MODEL=claude-opus-4-7` env. Cached at module load.

## Phases

### Phase 1 — Pivot + recon (H+0 to H+1)

Three parallel streams. Wave 1.

| Stream | Owner | Writes |
|---|---|---|
| Foreground: runtime pivot | Me (next session) | Delete Anthropic stack; create `agent/{SOUL,RULES,TOOLS,EXAMPLES}.md` from brandbook; create `src/agents/{system_prompt,claude_bridge}.py`; rewire `src/bot/handlers.py` to use bridge; rewrite root `CLAUDE.md` (project description); update `pyproject.toml` (deps); update `.env.example` |
| Background subagent: **brief-analyst** | Spawned via `Agent` tool | `docs/specs.md` (acceptance criteria for all 6 outcomes; cross-references to brandbook + sandbox MCP tool families) |
| Background subagent: **mcp-recon** | Spawned via `Agent` tool | `docs/mcp_inventory.md` (server reachability, full tool list with schemas, sample success + failure shapes for each tool family). Uses team token from `.claude/settings.local.json`. |

Phase 1 done when: bot replies via `claude -p`, persona loads from `agent/`, `docs/specs.md` and `docs/mcp_inventory.md` exist, all tests + ruff + mypy green.

### Phase 2 — Build (H+1 to H+8)

Two writers at a time, swap mid-phase.

| Wave | Foreground | Background subagent | Owns |
|---|---|---|---|
| 2a (H+1–4) | Me: runtime layer (`src/world/poller.py`, `src/workflows/*.py`, `src/webhooks/app.py` extensions for `/api/chat` + `/api/catalog`, `src/core/retry.py`, `src/core/voice.py`) | **coder-website** | `web/**` (new top-level Astro project): hero, menu, /cake/[slug], /custom, /policies; brand palette + Cormorant Garamond + Inter; chat widget; schema.org JSON-LD |
| 2b (H+4–8) | Me: integration + bug fixes | **coder-bot** | `src/bot/handlers.py` extensions, `src/bot/drafts.py` (new), `/dashboard`, `/budget`, order-notification handler, approval keyboards |

Phase 2 done when: end-to-end happy path works (Telegram message → `claude -p` → MCP tool → reply; website chat → `/api/chat` → `claude -p` → reply; world event → handler → reply); critic-style smoke check passes.

### Phase 3 — Integration + sleep window (H+8 to H+14)

Foreground: drive `world_start_scenario "first_day"` end-to-end through every channel; fix breakages. Self-grade via `evaluator_score_world_scenario`.

Sleep window for the human (~4h around H+10–14). During the window, background subagents run on:
- More product copy (brand-voice compliant, derived from `square_list_catalog`)
- Edge-case scenario YAMLs in `tests/scenarios/`
- README polish
- Asset captions

Phase 3 done when: every outcome has end-to-end evidence in audit log + MCP simulation state; no crashes during a full scenario run.

### Phase 4 — Critic + polish (H+14 to H+19)

Sequential 4-rubric critic via `Agent: critic` (one agent, four invocations: code-review, agent-friendliness, operator-ux, business-analyst). Each writes its section in `docs/critic_report.md`. Fix what's cheap.

Brand-voice pass on all customer-facing copy (`src/core/voice.py` linter + manual sweep).

Phase 4 done when: critic report has no high-severity items remaining within scope.

### Phase 5 — Submission (H+19 to H+22.5)

- `ARCHITECTURE.md` (required by brief): two-Claude pattern, MCP routing, owner-bot mapping, channel adapters, kitchen handoff, marketing loop
- `docs/MARKETING_PLAN.md`: $500 case with margin/AOV math
- `docs/DEMO.md`: clean-clone setup + scripted demo
- `README.md` final pass: setup, run, evaluate
- `.env.example` polished, no real secrets
- Final commit; verify repo public; submit form before May 10, 10:00 CT

## Subagent invocation plan

| Agent | When | Cwd | Writes (only) | Reads |
|---|---|---|---|---|
| `brief-analyst` | Phase 1 | repo root | `docs/specs.md` | `HACKATHON_BRIEF.md`, `HCU_BRANDBOOK.md`, `_workfiles/Sandbox pack…html`, `_workfiles/Team launch kit…html` |
| `mcp-recon` | Phase 1 | repo root | `docs/mcp_inventory.md` | `.claude/settings.local.json`, the configured MCP server (live calls) |
| `coder-website` | Phase 2a | `web/` | `web/**`, `package.json`, `astro.config.mjs`, `tailwind.config.cjs` | `agent/SOUL.md`, `assets/brand/**`, `HCU_BRANDBOOK.md`, `docs/specs.md` |
| `coder-bot` | Phase 2b | repo root | `src/bot/handlers.py`, `src/bot/drafts.py`, `tests/unit/test_drafts.py` | `agent/RULES.md`, `agent/TOOLS.md`, `docs/mcp_inventory.md`, `docs/specs.md` |
| `critic` (4 rubrics) | Phase 4 | repo root | sections of `docs/critic_report.md` | the whole repo |

Strict rule: no two subagents write to the same path at the same time.

## Quality gates

Pre-commit hook runs: `uv run ruff check src tests scripts examples` + `uv run mypy src` + `uv run pytest -q tests/unit`. Pushes are blocked on red.

Manual gates before each phase exit: live system runs the relevant flow without crashing; audit log shows the expected event sequence.

## Where the canonical sources live

| Topic | File | Audience |
|---|---|---|
| Brand voice + rules | `HCU_BRANDBOOK.md` | All; runtime via composed prompt |
| Hackathon brief | `HACKATHON_BRIEF.md` | All |
| Runtime persona | `agent/{SOUL,RULES,TOOLS,EXAMPLES}.md` | Runtime Claude (composed) |
| Project description | `CLAUDE.md` (rewritten) | Judges + devs + ambient runtime context |
| Architecture | `ARCHITECTURE.md` | Judges (required by brief) |
| Live execution plan | `docs/PLAN.md` (this file) | All |
| Internal handoff | `_workfiles/HANDOFF.md` | Future Claude sessions |
| MCP inventory | `docs/mcp_inventory.md` | Devs + agents |
| Specs | `docs/specs.md` | Devs + agents |
| Marketing $500 case | `docs/MARKETING_PLAN.md` | Judges |
| Demo evidence | `docs/DEMO.md` | Judges |
| Brand assets | `assets/brand/{logo,hero,products,social}/` | Website + social |

## Status

- **Today is May 9, 2026 (kickoff day).** Brief unsealed; team token in hand.
- **Last completed**: **Phase 3 — Integration (scripts + marketing plan + demo).**
  - `docs/MARKETING_PLAN.md` — $500/month plan across 5 channels (Meta Ads, Google Ads, boosted IG, GB / discovery, repeat / follow-up) with margin / AOV / conversion math + Sugar Land context. Backed by the executable mirror `scripts/seed_marketing.py`.
  - `scripts/run_scenario.py` — opens MCP, calls `world_start_scenario("launch-day-revenue-engine")`, drives `WorldPoller` while periodically calling `world_advance_time` to skip simulator time, then self-grades via the five `evaluator_score_*` tools and `evaluator_get_evidence_summary`. Writes `data/scorecard_<timestamp>.json`.
  - `scripts/seed_marketing.py` — runs the closed loop: budget read → 2 campaigns (Mother's Day Meta + local-search Google) → launch → leads → route each lead → adjust → metrics → owner report. **Smoke-tested live**: 2 campaigns, 6 leads, ~62 audit calls, all MCP tools 200 OK.
  - `scripts/seed_review_replies.py` — reads `gb_list_reviews`, asks the bridge for a brand-voice reply per review, posts via `gb_simulate_reply`. **Smoke-tested live**: 4/4 reviews replied (incl. the negative `rev_003`).
  - `scripts/seed_drafts.py` — generates one IG post per brandbook content group (Product / Audience / Company), schedules each via `instagram_schedule_post`, persists locally so `/drafts` Telegram command can list / approve them.
  - `scripts/demo.sh` — single-shot end-to-end orchestrator: starts uvicorn → runs all four seed scripts → drives the world scenario → calls `evaluator_generate_team_report` → saves to `data/team_report.json`. The submission demo target.
  - `docs/DEMO.md` — operator runbook from clean clone to artefacts.
  - Backend kept clean: ruff clean, mypy --strict clean, **103 pytests green**.
- **Phase 2 (prior)**: runtime layer (retry, voice linter, drafts table, orchestrator), storefront API (`/api/catalog`, `/api/policies`, `/api/chat`, `/api/lead`), world poller, owner Telegram commands (`/dashboard`, `/budget`, `/drafts`), Astro storefront (8 routes + JSON-LD + chat widget). Commit `2dfbe13`.


  - Web/backend API contract locked at `docs/CONTRACTS.md`.
  - **Backend**: `src/core/retry.py` (exponential backoff + jitter), `src/core/voice.py` (brand-voice linter covering brand.r1..r10), `src/mcp/http_client.py` (HTTPS+JSON-RPC client for the happycake server with envelope unwrap + retry wrapper), `src/storage/drafts.py` + migration `002_drafts.sql` (drafts queue, owner identity, leads table), `src/workflows/orchestrator.py` (channel-agnostic per-turn orchestrator wrapping the bridge with audit + voice-lint).
  - **World engine**: `src/world/poller.py` (event polling loop) with channel-specific dispatchers for `whatsapp`, `instagram_dm`, `instagram_comment`. Events drive the orchestrator and reply via `whatsapp_send` / `instagram_send_dm` / `instagram_reply_to_comment`.
  - **Storefront API** (in `src/webhooks/app.py` + `src/webhooks/storefront.py`): `GET /api/catalog` (square_list_catalog + kitchen_get_capacity → contract shape), `GET /api/policies` (brandbook-derived static), `POST /api/chat` (orchestrator + bridge), `POST /api/lead` (persists + best-effort `marketing_report_to_owner`). CORS for the Astro origin. Returns 503 / 502 on contract errors.
  - **Owner Telegram bot**: `/dashboard` (POS + kitchen + evaluator summaries), `/budget` (marketing budget + recent leads), `/drafts` (lists pending with Approve / Edit / Reject inline keyboard; Approve triggers `instagram_approve_post` + `instagram_publish_post` for IG drafts). `/start` captures the owner's chat id idempotently. `BOT_COMMANDS` extended; menu re-synced.
  - **Website (`web/`)**: Astro + Tailwind, 8 pages (`/`, `/cake/[slug]`, `/about`, `/policies`, `/order`, `/custom`, `/guides/cake-for-x-guests`, `/sitemap.xml`), `/catalog.json`, `/robots.txt`, JSON-LD Product+Offer on every product page, vanilla-JS chat widget posting to `/api/chat`. Brandbook palette + Cormorant Garamond + Inter. `npm run build` exits 0; `tsc --noEmit` clean. Asset pack copied from `assets/brand/` to `web/public/brand/` at build time. Fallback catalog so the build succeeds even when the backend is offline.
  - **Tests**: 7 new test modules (retry, voice, drafts, orchestrator, storefront, world_poller, webhook_routes) — 58 new test cases. Quality gate: ruff clean, mypy --strict clean, **103 pytests green**.
- **Next**: Phase 4 — Critic sweep (4 rubrics: code-review, agent-friendliness, operator-ux, business-analyst) + brand-voice polish on committed copy. Then Phase 5 — Submission (`ARCHITECTURE.md`, README final pass, repo public, submit).
- **Background processes**: nothing running. To bring it up, see `docs/DEMO.md` §3.

This file gets updated by every Phase exit and at every commit boundary.
