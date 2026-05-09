# Critic report — 2026-05-09

> Read-only audit. Each section is one of the four AI-evaluator passes the
> hackathon scoring uses. Findings cite file:line. Severity tags: CRIT
> (regression-risk), HIGH (visible scoring miss), MED (polish), LOW (nit).

**Total**: 13/15 + 13/15 + 13/15 + 9/10 = **48/55** for the 3 code-style passes
and business-analyst (excludes functional-tester, on-site-assistant, innovation
which are external). Composite within this audit: **48/55**.

Pre-checks — `uv run ruff check src tests` clean; `uv run mypy src` clean
(40 files, strict); `uv run pytest` 103 passed in ~2.4s; all 28 `src/**/*.py`
files under 500 lines (largest: `src/storage/drafts.py:316`).

---

## 1. Code Reviewer  13/15

### Strengths
1. **Layered DDD with one job per module.** Hard split `agents/` (LLM bridge),
   `mcp/` (transport), `workflows/orchestrator.py` (per-turn), `world/poller.py`
   (event loop), `bot/` (handlers/middleware/storage), `webhooks/` (FastAPI),
   `storage/` (repos), `core/` (config/retry/voice/errors/logging). The
   orchestrator (`src/workflows/orchestrator.py:56-119`) is the right seam —
   channel-agnostic, pure runtime persona + audit + voice-lint.
2. **Quality gates green.** `pyproject.toml:71-79` enables mypy `strict =
   true`, ruff has B/S/SIM/PL/ASYNC enabled
   (`pyproject.toml:42-58`), 103 tests pass with a clean injection seam:
   tests pass a `runner` callable into `ClaudeBridge`
   (`src/agents/claude_bridge.py:33-36`) and a `FakeMcpClient` into `AppDeps`
   (`tests/unit/test_webhook_routes.py:25-65`) — no real LLM/MCP calls in unit
   tests, exactly the discipline `CLAUDE.md` mandates.
3. **Idempotency, retry, structured errors at the boundaries.**
   `src/core/retry.py:29-77` (typed exponential backoff + injectable sleeper +
   RNG), `src/storage/idempotency.py`, `src/core/errors.py` (`ToolResult`
   TypedDict + `ok/not_found/error` helpers), `src/mcp/http_client.py:45-56`
   distinguishing `McpTransportError` (retryable) from `McpError` (terminal).

### Weaknesses
1. **Owner Telegram subsystem only logs failures, never tells the owner.**
   In `src/bot/owner_commands.py:170-199` the publish path swallows
   `McpTransportError`/`McpError` into a `publish_note` string and edits the
   message — but the audit `record(...)` only carries `draft_action: "approve"`
   without surfacing `publish_failed`. Severity: MED. Easy fix: add a second
   `record(... "publish_status": "failed", "reason": str(exc))`.
2. **`webhooks/app.py:109` is `# noqa: PLR0915` (too-many-statements).**
   `build_app` is 200+ lines of nested route closures — the ergonomic cost is
   that adding a route requires reading the whole factory. Severity: LOW.
   Routes could split into `register_storefront(app, deps)` /
   `register_webhooks(app, deps)`.
3. **`src/bot/handlers.py:109-118` records the assistant outbound but does not
   run the brand-voice linter that the orchestrator runs.** Telegram-side
   replies bypass `src.core.voice.lint` (the orchestrator does it at
   `src/workflows/orchestrator.py:88-101` for website/whatsapp/instagram). The
   bot is owner-facing so brandbook §7 says replies don't need approval, but
   the linter is also the mechanism for catching wordmark drift the owner
   reads — losing it on Telegram costs evidence in the audit log. Severity:
   MED.
4. **Two `except Exception` at boot (`src/webhooks/app.py:121,131`,
   `src/bot/app.py:75`)** — covered by `# pragma: no cover` and ringfenced to
   lifespan; defensible but worth narrowing to `(McpError, McpTransportError,
   RuntimeError)` for hygiene. Severity: LOW.
5. **`tests/scenarios/` directory is missing** even though
   `tests/unit/test_scenarios.py` exists for the YAML harness. The harness
   self-tests pass but no real workflow scenario YAMLs ship in `tests/`. The
   world engine (`scripts/run_scenario.py`) and seed scripts are the de-facto
   integration suite. Severity: LOW (scope: PLAN.md gap-fix #9 explicitly
   labels this two-layer; world engine is the integration backbone).

### Action items (priority order)
- [ ] MED — Surface MCP publish failures in audit + UX
      (`src/bot/owner_commands.py:170-199`); add a `record("system",
      "draft_publish_failed", …)` so the owner has evidence.
- [ ] MED — Run `lint(LintRequest(...))` on the `claude -p` reply in
      `src/bot/handlers.py:99-104` and log `voice_warnings` to audit.
- [ ] LOW — Split `src/webhooks/app.py:109` `build_app` into 3-4 register
      helpers; remove the `# noqa: PLR0915`.
- [ ] LOW — Add at least one workflow YAML under `tests/scenarios/` (e.g.
      `w4_whatsapp_honey_inquiry.yaml`) so the existing harness runner has a
      real fixture; mirrors specs.md w4 fixtures.

---

## 2. Agent-Friendliness Auditor  13/15

### Strengths
1. **Runtime persona is split into four single-job files** (`agent/SOUL.md`,
   `RULES.md`, `TOOLS.md`, `EXAMPLES.md`) and composed deterministically by
   `src/agents/system_prompt.py:39-50` with `lru_cache`, joined with stable
   `## SOUL`/`## RULES`/etc. headings — a runtime model can refer to each
   section by name. Hard rules in `agent/RULES.md:1-49` are absolute and
   include `idempotency_key` (rule 11), kitchen-capacity precondition (rule 7),
   no fabrication (rule 5), MCP-first (rule 6). Verb-noun guidance throughout.
2. **w2 acceptance criteria all built and reachable.** w2.ac1 — JSON-LD
   `Product`+`Offer` at `web/src/pages/cake/[slug].astro:76-93` with
   `availability` driven by `kitchen.overCapacity`. w2.ac2 —
   `web/src/pages/catalog.json.ts` returns the full catalog with structured
   error `{"error": "catalog_unavailable"}` (w2.ec1). w2.ac3 — `/api/policies`
   in `src/webhooks/storefront.py:131-200` enumerates pickup, delivery,
   lead_times, refunds, allergens, halal with stable `id`s. w2.ac5 —
   `web/public/robots.txt` and `web/src/pages/sitemap.xml.ts` both present.
   URLs follow `/cake/[slug]`, `/policies`, `/order`, `/custom`,
   `/guides/cake-for-x-guests`.
3. **TOOLS.md is operationally precise.** `agent/TOOLS.md:21-156` has
   when-to-use, gotchas (e.g. `kitchenProductId` vs `variationId`,
   `square_recent_sales_csv` returns CSV not JSON, `instagram_send_dm` accepts
   any `threadId`), idempotency callouts, and family-level when-NOT-to-use
   ("These tools are not for customer-visible flows" for `world_*` and
   `evaluator_*`). Closing pattern + escalation triggers are in `RULES.md`.

### Weaknesses
1. **`/catalog.json` is built at static-build time only — when the build runs
   without a backend, the file shipped in `web/dist/catalog.json` is the
   error envelope `{"error":"catalog_unavailable",...}` and its HTTP status is
   200.** Verified: `web/dist/catalog.json` literally contains the error
   string. An autonomous AI customer crawling the deployed site at clean-clone
   demo time would read an "updating the menu" payload, not products. The
   fallback baked into `[slug].astro:20-53` only saves product *pages*, not
   `/catalog.json`. Severity: HIGH (this directly hits w2.ac2 / agent-readable
   catalog). Cheap fix: have `web/src/pages/catalog.json.ts:21` fall back to
   the same `FALLBACK_PRODUCTS` array when `fetchCatalog()` returns null.
2. **TOOLS.md and the runtime persona reference `kitchen_get_capacity`
   (rule 7 in `agent/RULES.md:26`, family table in `agent/TOOLS.md:51`),
   but `agent/RULES.md` brand.r9 in `docs/specs.md:25` and the audit-log
   evidence requirement say `kitchen_get_production_summary`** — the runtime
   sees both names. The runtime will probably call whichever it sees first,
   but the audit-log probe checks for `production_summary` per the spec.
   Severity: MED. Easy fix: add a one-liner to `agent/RULES.md:26` clarifying
   "either tool satisfies the precondition; prefer `kitchen_get_capacity` for
   timing, `kitchen_get_production_summary` for owner summaries."
3. **No `manifest.json` / `humans.txt` / `agent.txt` machine hint that names
   `/catalog.json` and `/api/policies` as the agent surfaces.** `robots.txt`
   only has `Sitemap:`; `sitemap.xml` lists pages but not the JSON. An LLM
   crawling cold has to guess. Severity: LOW (judges' crawler reads the
   sitemap anyway).
4. **`src/webhooks/app.py` uses `# docs_url=None, redoc_url=None`
   (`webhooks/app.py:147-148`)** — disables OpenAPI. For a backend that is
   nominally agent-friendly that is the wrong default; a `/openapi.json`
   would be free w2 evidence. Severity: LOW.

### Action items (priority order)
- [ ] HIGH — Have `web/src/pages/catalog.json.ts` reuse the same
      `FALLBACK_PRODUCTS` shape as `web/src/pages/cake/[slug].astro:20-53`
      so the static `/catalog.json` is non-empty when the backend was offline
      at build time.
- [ ] MED — Reconcile `kitchen_get_capacity` vs `kitchen_get_production_summary`
      naming in `agent/RULES.md:26-31`, `agent/TOOLS.md:51`, and
      `docs/specs.md:25` so the audit probe and the persona agree on which
      tool name evidences brand.r9.
- [ ] LOW — Re-enable `/openapi.json` in `src/webhooks/app.py:147-148`
      (delete `docs_url=None, redoc_url=None`); free agent-readability.
- [ ] LOW — Add `web/public/agent.txt` listing
      `/catalog.json`, `/api/policies`, `/sitemap.xml`, `/cake/<slug>` JSON-LD.

---

## 3. Operator UX Simulator  13/15

### Strengths
1. **`BOT_COMMANDS` is synced to Telegram on boot** (`src/bot/app.py:24-38`)
   so the Menu button shows `/start /help /dashboard /budget /drafts /cancel
   /restart`. `cmd_help` text in `src/bot/handlers.py:25-34` matches the
   command list exactly. `/cancel` reports prior state; `/restart` clears
   sessions; both are state-machine-correct (`handlers.py:62-79`).
2. **Ack-then-work is implemented.** `src/bot/handlers.py:95` calls
   `bot.send_chat_action(message.chat.id, "typing")` *before* the bridge
   subprocess; failure mode delivers "I couldn't reach the model just now —
   please try again in a moment." (`handlers.py:101-104`) — human-readable,
   no stack trace.
3. **FSM survives restart.** `SqliteFsmStorage` (`src/bot/storage.py:19-78`)
   persists state in the `fsm_state` SQLite table; `Dispatcher` constructed
   with this storage at `src/bot/app.py:51`. `/start` writes owner identity
   idempotently (`src/storage/drafts.py:193-208`, `INSERT … ON CONFLICT(id)
   DO UPDATE`). The drafts queue (`/drafts` flow) approves via inline-keyboard
   (`src/bot/keyboards.py:13-32`, ≤3 buttons → fits the brief's "≤6 options
   inline" guideline) and Approve actually drives
   `instagram_approve_post` + `instagram_publish_post` end-to-end with publish
   feedback (`src/bot/owner_commands.py:175-199`).

### Weaknesses
1. **`/dashboard`, `/budget`, `/drafts` send no "working…" placeholder
   while three sequential MCP calls run.** `src/bot/owner_commands.py:35-79`
   issues three `_summary_block` calls (each with its own retry envelope) before
   the first byte to the user; on a 3-attempt retry per call, the user can
   wait 5-10s with no feedback. Severity: HIGH (operator-UX rubric explicitly
   scores ack within 2s for long ops). Cheap fix: send a "fetching dashboard…"
   `message.answer` first, then edit it, OR call
   `bot.send_chat_action(chat_id, "typing")` before each `_summary_block`.
2. **`/drafts` Edit flow does not capture edit text.** Tapping Edit posts
   `"(owner requested edit — re-generate)"` as the static edit text
   (`src/bot/owner_commands.py:147-152`) — there's no FSM follow-up that
   reads the next user message as the edit. The PLAN.md gap-fix #2 says
   "owner approves in Telegram before publication"; Edit is a documented
   v2 in the comment but the spec calls for it (`docs/specs.md:489`,
   w5.ec1). Severity: MED.
3. **Owner-bot Markdown renders user-controlled JSON inside ``` blocks
   (`src/bot/owner_commands.py:215`).** If MCP returns a string containing
   ```` ``` ```` the markdown will break and Telegram will 400. Defensive:
   `_pretty(...).replace("```", "''")` or use HTML parse mode for these
   blocks since the bot already sets `ParseMode.HTML` as default
   (`src/bot/app.py:47`) — but `cmd_dashboard`/`cmd_budget` override with
   `parse_mode="Markdown"`. Severity: LOW.
4. **No "/help always works" guarantee.** `/help` is a `Command("help")`
   handler (`src/bot/handlers.py:55`) but it is only registered on the
   `commands_router`, included *after* `owner_router` (`bot/app.py:54-55`).
   The owner router has no `/help` so it falls through correctly, but if
   the orchestrator/FSM ever stalls the inbound, `/help` still works because
   it's a typed Command filter not text — fine. The risk is the AuditMiddleware
   creating a session before any handler runs (`src/bot/middleware.py:28`)
   on every inbound; if SQLite is locked, the middleware blocks. Severity:
   LOW.

### Action items (priority order)
- [ ] HIGH — Add an immediate `await message.answer("Fetching dashboard…")`
      ack at the top of `cmd_dashboard`, `cmd_budget`, `cmd_drafts` in
      `src/bot/owner_commands.py:35,58,83`, then `await ack.edit_text(...)`
      with the result.
- [ ] MED — Wire an FSM state for the Edit branch in
      `src/bot/owner_commands.py:146-162`: set state `await
      state.set_state(EditDraft.awaiting_text)`, capture the next text
      message, store it via `drafts.edit(draft_id, edit_text)`, requeue.
- [ ] LOW — Defensive escape of triple-backticks in `_pretty`
      (`src/bot/owner_commands.py:218-224`).

---

## 4. Business Analyst  9/10

### Strengths
1. **Sugar Land context is concrete and brandbook-anchored.**
   `docs/MARKETING_PLAN.md:16-31` cites $110K median income, multicultural
   family base (Anglo + Hispanic + South/Central Asian), brandbook Appendix B
   peaks (Mother's Day, Thanksgiving, Christmas, Eid, Nauryz), and the
   community-trust-over-paid insight specific to the diaspora segment. Not
   generic.
2. **Margin/AOV/conversion math present and self-consistent.**
   `MARKETING_PLAN.md:39-82` lays out per-product margins from
   `marketing_get_margin_by_product`, $18k/month historic baseline at $25 AOV
   from `marketing_get_sales_history`, blended 65% margin → $769 break-even
   on $500 spend → $5,000 = 10× spend bar. The per-channel CTR/conversion
   table (`MARKETING_PLAN.md:71-78`) sums to ~200 orders / ~$5,000 with
   conservative AOV. Allocations sum to **exactly $500**: $180+$120+$80+$40+$80
   (verified). Calendar table at lines 148-154 also reconciles to $500/week
   sums.
3. **Executable mirror is consistent with the doc.** `scripts/seed_marketing.py:40-81`
   creates two flagship campaigns whose `name`, `budgetUsd`, `objective`,
   `targetAudience`, `offer`, `landingPath` text match the plan word-for-word
   ($180 Mother's Day Meta and $120 Google local search), routes leads with
   per-channel reasons, calls `marketing_adjust_campaign` per the plan's
   §6 cadence, and ends with `marketing_report_to_owner`. Channels covered:
   Meta Ads, Google Ads, boosted IG, GB / discovery, repeat — **5 of 7
   listed**, exceeding the brief's "≥4 channels". Calendar tied to brandbook
   Appendix B (`MARKETING_PLAN.md:148-160`). Limitations explicit
   (`§7`: no real ad creds, no SMS, no email MVP, no over-cap).

### Weaknesses
1. **The plan claims the IG-boost channel pulls $80 but the executable mirror
   only creates the Meta + Google campaigns.** `scripts/seed_marketing.py:40`
   has `PLAN: list = [Mother's Day Meta, Google local]` — channels 3, 4, 5
   (boosted IG, GB discovery, repeat/follow-up) have no
   `marketing_create_campaign` call. The owner report will count 2 campaigns,
   not 5. Severity: MED. Cheap fix: add 3 more PLAN entries (or document in
   `docs/MARKETING_PLAN.md:165` that #3-5 are organic/non-paid-budget and
   live outside `marketing_create_campaign`, executed via
   `seed_drafts.py` + `seed_review_replies.py`).
2. **Margin numbers are presented as "Est." but no source attribution to the
   live `marketing_get_margin_by_product` call.** `MARKETING_PLAN.md:39-46`
   lists 68%, 64-66%, 62%, 60%, 58% — close to TOOLS.md's "~64-68% on honey
   + pistachio slices" (`agent/TOOLS.md:75`) but the doc says "live"
   (`MARKETING_PLAN.md:36-38`) while the table reads as static. Severity: LOW.

### Action items (priority order)
- [ ] MED — Add the three missing channels (boosted IG, GB discovery,
      repeat/follow-up) to `scripts/seed_marketing.py:40` `PLAN` list, or
      explicitly note in `docs/MARKETING_PLAN.md:114` that they are organic /
      external to the simulator and call out which scripts cover them
      (`seed_drafts.py`, `seed_review_replies.py`).
- [ ] LOW — In `docs/MARKETING_PLAN.md:39-46`, label the margin column with
      "(snapshot YYYY-MM-DD)" or "(seeded sandbox)" so judges don't expect
      live numbers from a static table.

---

## Top 5 cheapest fixes (≤30 min each)

1. **Restore non-empty `/catalog.json` fallback** —
   `web/src/pages/catalog.json.ts:21` — copy the `FALLBACK_PRODUCTS` array
   from `web/src/pages/cake/[slug].astro:20-53` and return it when
   `fetchCatalog()` returns null. Impact: agent-friendliness scoring on a
   clean-clone build (HIGH).
2. **Ack `/dashboard`, `/budget`, `/drafts` immediately** —
   `src/bot/owner_commands.py:35,58,83` — add a one-line "Fetching
   dashboard…" `message.answer` at the top of each, edit it on completion.
   Impact: Operator UX latency rubric (HIGH).
3. **Reconcile `kitchen_get_capacity` vs `kitchen_get_production_summary`** —
   `agent/RULES.md:26-31`, `agent/TOOLS.md:51`, `docs/specs.md:25` — single
   one-line clarification so brand.r9 evidence in `mcp_audit_log` matches
   what the runtime actually calls (MED).
4. **Add the 3 missing marketing channels to the seed script** —
   `scripts/seed_marketing.py:40` `PLAN` list, or document that channels
   3-5 are organic and live in `seed_drafts.py` / `seed_review_replies.py`.
   Closes the doc-vs-execution gap that BA scoring penalises (MED).
5. **Lint Telegram free-text replies for brand-voice** —
   `src/bot/handlers.py:99-104` — call
   `lint(LintRequest(text=reply_text, channel="telegram"))` and `record(...)`
   warnings to audit; the orchestrator already does this for other channels.
   Impact: code-review consistency + audit evidence (MED).
