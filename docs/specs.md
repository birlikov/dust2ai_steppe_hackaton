# HappyCake AI — Acceptance Specifications

> Source of truth: `HACKATHON_BRIEF.md` (event brief) and `HCU_BRANDBOOK.md` (brand book v1.0). Tool catalog from `_workfiles/Sandbox pack · Steppe Business Club.html` and `_workfiles/Team launch kit · Steppe Business Club.html`.
>
> Every acceptance criterion is testable and traces back to a quoted constraint. Stable IDs (`w<n>.ac<m>` and `w<n>.ec<m>`) are referenced by the Functional Tester evaluator (20 pts).
>
> MCP server: `https://www.steppebusinessclub.com/api/mcp` with `X-Team-Token` header. Tool families: `marketing_*`, `kitchen_*`, `square_*`, `world_*`, `evaluator_*`.

---

## Cross-cutting brand hard rules (apply to every customer-facing workflow: w3, w4, w5, w6)

These are reproduced from `HCU_BRANDBOOK.md` §7 and §2 verbatim. Each is enforceable per outbound payload via `src/core/voice.py` (brand-voice linter, gap-fix #7). Tests can probe any workflow against any rule.

| ID | Rule | Source |
|---|---|---|
| brand.r1 | "Always English. Never reply in another language even if the customer writes in one." | brandbook §7 hard rule 1 |
| brand.r2 | "Wordmark spelling. Always *HappyCake*. Never *Happy Cake*, *HC*, *happycake*, *HAPPYCAKE*." | brandbook §7 hard rule 2 + §2 wordmark rules |
| brand.r3 | "Cake names in quotes after 'cake'." e.g., *cake "Honey"*, *cake "Napoleon"*. | brandbook §7 hard rule 3 |
| brand.r4 | "Three emojis maximum, ever. Often zero." | brandbook §7 hard rule 4 |
| brand.r5 | "No fabrication. If the agent doesn't know, it asks the inventory MCP, the product-catalog MCP, or the human. It never invents a price, a flavour, an ingredient, a policy, or a hour." | brandbook §7 hard rule 5 |
| brand.r6 | "No publishing without approval. Drafts go into the approval queue. The owner approves in Telegram before publication." | brandbook §7 hard rule 6 |
| brand.r7 | "Never delete a customer comment, on any channel." | brandbook §7 hard rule 7 |
| brand.r8 | "Closing every post the same way. *Order on the site at happycake.us or send a message on WhatsApp.* (Adjust phone number / link as needed, but the pattern stays.)" | brandbook §2 editorial rule 8 |
| brand.r9 | Kitchen-capacity precondition: every availability/timing answer requires a prior `kitchen_get_production_summary` call (project locked decision; brandbook §7 hard rule 5 forbids invented availability). | `docs/PLAN.md` gap-fix #3 |
| brand.r10 | "We sit toward [emotional, witty, open, simple, humble, modern]" — voice tone scale. | brandbook §2 |
| brand.r11 | "No abbreviations except standard units" (m, cm, g, kg, pcs., min., oz.). | brandbook §2 editorial rule 6 |
| brand.r12 | "Specific quantities" — *Cake "Honey" — 1.2 kg, $42*, not vague phrasing. | brandbook §2 editorial rule 7 |

---

## w1 — Website / Storefront

```yaml
workflow:
  id: w1
  name: Website / Storefront (happycake.us)
  goal: "Build happycake.us as a real sales site that lets a Sugar Land customer move from interest to order intent without scraping or guessing."
  primary_actor: Customer
  channel: Website
  inputs:
    - name: catalog data
      type: structured product list (id, name, slug, price, weight, ingredients, photo, halal flag, lead_time)
      source: square_list_catalog (MCP)
    - name: kitchen capacity
      type: production summary (today's queue, capacity remaining, lead times)
      source: kitchen_get_production_summary (MCP)
    - name: pricing
      type: USD price + size string per product
      source: square_list_catalog (MCP)
    - name: photos
      type: 22 optimized hero/product/social images
      source: /hackathon-assets/happy-cake/ (asset pack referenced in brief §7 + sandbox HTML)
    - name: campaign attribution params
      type: URL query string (?utm_source=, ?utm_campaign=)
      source: inbound HTTP request to landing page
    - name: lead form submissions
      type: name, contact, intent, attribution
      source: customer form on website
  acceptance_criteria:
    - id: w1.ac1
      given: "Brief §3 lists Website needs: catalog, prices, product photos, order path, pickup/delivery or availability logic, clear policies, useful content for customers, structure that AI agents can read without brittle scraping."
      when: a judge loads happycake.us from a clean clone
      then: every listed element (catalog, prices, photos, order-intent path, pickup/delivery policy, customer policies page, content section) is present and reachable from the homepage
    - id: w1.ac2
      given: brief §3 "It should have ... prices"
      when: a customer opens any product page
      then: the displayed price comes from a `square_list_catalog` call at build or request time and exactly matches the catalog's value (no hardcoded number)
    - id: w1.ac3
      given: brief §3 "pickup/delivery or availability logic"
      when: a customer selects a cake and asks about availability
      then: the page or assistant cites kitchen capacity (from `kitchen_get_production_summary`) and either offers a pickup window respecting that capacity or refuses with reason
    - id: w1.ac4
      given: sandbox pack "Campaign landing pages and attribution for Marketing Simulator traffic"
      when: traffic arrives at any landing page with `?utm_source=...&utm_campaign=...`
      then: the attribution is parsed, persisted with any subsequent lead, and reported via `marketing_report_to_owner` on submit
    - id: w1.ac5
      given: brandbook §4 visual identity (palette tokens `happy-blue-{900,700,500,200}`, `cream-{50,100,200}`, accents) and typography (Cormorant Garamond + Inter)
      when: any page renders
      then: the page uses the brandbook palette tokens and the two specified font families exclusively for headings/body
    - id: w1.ac6
      given: brandbook wordmark rule (§2) — "HappyCake. One word. Two capital letters: H and C."
      when: the brand name appears anywhere in copy on the site
      then: it is spelled exactly "HappyCake" — never "Happy Cake", "happycake", "HAPPYCAKE", or "HC" (covers brand.r2)
    - id: w1.ac7
      given: brandbook §2 closing pattern "Order on the site at happycake.us or send a message on WhatsApp."
      when: any product page or marketing surface closes its CTA
      then: the closing sentence appears verbatim or with only the explicitly-allowed phone/link substitution (covers brand.r8)
    - id: w1.ac8
      given: brief §3 "useful content for customers"
      when: a visitor browses content beyond the catalog
      then: at least one page exists drawing on brandbook content groups (Product / Company / Audience) — e.g., "How to choose a cake for X guests" — and is discoverable from navigation
    - id: w1.ac9
      given: brief §3 "clear policies"
      when: a visitor or AI agent looks for refunds/allergens/pickup/delivery rules
      then: a `/policies` page (or equivalent stable URL) lists these explicitly and is linked from the footer
    - id: w1.ac10
      given: brandbook §2 editorial rule 7 "Specific quantities"
      when: a product card displays size and price
      then: weight (kg) and price (USD) are shown in the form `1.2 kg, $42` (covers brand.r12)
    - id: w1.ac11
      given: brief §3 "product photos" + brandbook §4 "Always real. Never stock photography. Never AI-generated photos of the product"
      when: any product photo is rendered
      then: the source is the approved asset pack at `/hackathon-assets/happy-cake/` — no AI-generated cake imagery
  edge_cases:
    - id: w1.ec1
      given: catalog API is unreachable
      when: a page tries to render a product list
      then: the page surfaces a graceful "We're updating the menu" message instead of fabricating prices (per brand.r5)
    - id: w1.ec2
      given: a product is in catalog but kitchen production is at capacity
      when: a visitor opens that product
      then: the order CTA reflects "ordering closed for today" or proposes a later day, never silently accepts an over-capacity order
    - id: w1.ec3
      given: a cake-name string appears on a page (e.g., "Honey")
      when: the page renders
      then: it is rendered as `cake "Honey"` (brand.r3 — quotes, capitalised, after the word "cake")
  data_dependencies:
    - square_list_catalog (read)
    - kitchen_get_production_summary (read)
    - marketing_report_to_owner (write — on lead form submit)
    - asset pack `/hackathon-assets/happy-cake/` (static)
  out_of_scope:
    - real Square or payment-processor integration (brief §4 forbids real payment credentials)
    - custom user accounts / login (brief and brandbook silent; "single-tenant sandbox")
    - multi-language site copy (brand.r1: English only)
    - real shipping carrier integration
    - "unspecified" — order persistence beyond `square_create_order` simulator side effects
```

---

## w2 — Agent-friendly site

```yaml
workflow:
  id: w2
  name: Agent-friendly website
  goal: "Make happycake.us readable and completable by an autonomous customer-side AI agent without brittle scraping."
  primary_actor: Agent system (customer-side AI)
  channel: Website / API
  inputs:
    - name: rendered HTML pages
      type: server-rendered HTML with semantic structure
      source: w1 site
    - name: structured product data
      type: JSON-LD Product + Offer schema embedded per product page
      source: square_list_catalog (MCP) → page template
    - name: machine-readable catalog
      type: /catalog.json endpoint (gap-fix from PLAN.md outcome 2)
      source: square_list_catalog (MCP)
    - name: policies
      type: human-readable + machine-discoverable text
      source: w1 /policies page
    - name: order-intent path
      type: stable URLs and form schemas
      source: w1 site
  acceptance_criteria:
    - id: w2.ac1
      given: brief §3 "product data is readable"
      when: an AI agent fetches any product page
      then: the page contains valid Schema.org `Product` + `Offer` JSON-LD with name, price, priceCurrency, availability, image
    - id: w2.ac2
      given: brief §3 "prices and constraints are clear"
      when: an AI agent fetches the catalog
      then: a `/catalog.json` (or equivalent stable JSON endpoint) returns the full product list with price, weight, lead_time, allergens, halal flag derived from `square_list_catalog`
    - id: w2.ac3
      given: brief §3 "policies are explicit"
      when: an AI agent fetches `/policies`
      then: the policies page enumerates pickup, delivery, refunds, allergens, lead times in plain English, with stable headings
    - id: w2.ac4
      given: brief §3 "order-intent path is discoverable"
      when: an AI agent traverses from homepage
      then: it can reach an order-intent submission form within ≤3 clicks/links, with form fields labeled (name, contact, item, qty, pickup/delivery, date)
    - id: w2.ac5
      given: brief §3 "pages are structured enough for automated browsing and extraction"
      when: an AI agent crawls the site
      then: URLs follow a predictable pattern (e.g., `/cake/[slug]`, `/policies`, `/order`, `/custom`) and a `robots.txt` + `sitemap.xml` are present
    - id: w2.ac6
      given: sandbox pack "agent friendliness: can an AI customer read the site, understand constraints, and reach order intent?"
      when: an autonomous AI customer is run end-to-end against the site
      then: it can complete an order-intent submission without human intervention and the resulting record carries enough fields for `square_create_order` + `kitchen_create_ticket`
  edge_cases:
    - id: w2.ec1
      given: an agent requests `/catalog.json` while `square_list_catalog` is rate-limited or down
      when: the endpoint cannot fetch fresh data
      then: it returns HTTP 503 with a JSON error body (not a stale or fabricated catalog)
    - id: w2.ec2
      given: an agent submits the order-intent form with missing required fields
      when: the form is processed
      then: a 4xx response with field-level errors is returned (no silent acceptance)
  data_dependencies:
    - square_list_catalog (read, primary)
    - kitchen_get_production_summary (read, for availability fields)
  out_of_scope:
    - GraphQL or other custom protocols beyond JSON-LD + REST JSON
    - agent-authentication flows (sandbox is single-tenant)
    - LLM tool-use over the site (the assistant surface is w3)
    # AMBIGUOUS: brief §3 "structure that AI agents can read without brittle scraping" vs sandbox HTML "agent friendliness: can an AI customer read the site, understand constraints, and reach order intent" — interpretation A: only static structure (JSON-LD + /catalog.json). Interpretation B: also a programmatic ordering API. Default to A per brief silence on a public ordering API.
```

---

## w3 — On-site assistant

```yaml
workflow:
  id: w3
  name: On-site assistant (chat widget on happycake.us)
  goal: "Let a website visitor get product guidance, custom-cake consultation, event planning, complaint handling, order-status, and owner escalation, using sandbox evidence and site data only."
  primary_actor: Customer
  channel: Website (chat widget → /api/chat → claude_bridge → MCP)
  inputs:
    - name: customer message
      type: free-text chat input
      source: chat widget HTTP POST to /api/chat
    - name: catalog
      type: product list with prices, sizes, ingredients, halal flags
      source: square_list_catalog
    - name: kitchen state
      type: production summary, capacity, queue, lead times
      source: kitchen_get_production_summary
    - name: policies
      type: pickup/delivery/refund/allergen rules
      source: w1 /policies static text passed via system prompt
    - name: brand voice
      type: agent persona (SOUL/RULES/TOOLS/EXAMPLES)
      source: agent/*.md composed by src/agents/system_prompt.py
    - name: owner Telegram chat
      type: bot connection for escalation
      source: src/bot (aiogram polling)
  acceptance_criteria:
    - id: w3.ac1
      given: brief §3 on-site assistant "must use sandbox evidence and site data. It should not invent facts."
      when: a customer asks any factual question (price, flavor, availability, policy)
      then: the assistant calls the relevant MCP tool BEFORE answering and cites it (covers brand.r5)
    - id: w3.ac2
      given: brief §3 useful scenario "product guidance"
      when: a customer asks "what cake for 10 guests?"
      then: the assistant queries `square_list_catalog`, applies brandbook reference 2 logic (1 slice/person + 3 extras → 1.2 kg), and recommends one or more cakes by name
    - id: w3.ac3
      given: brief §3 "custom cake consultation"
      when: a customer asks for a custom cake (size/text/decoration)
      then: the assistant captures requirements and escalates to owner via Telegram, with all MCP-derived evidence attached, BEFORE promising delivery (brandbook §1 positioning "We are not custom cakes. Decoration is a small, optional service.")
    - id: w3.ac4
      given: brief §3 "event planning"
      when: a customer describes an event (date, guest count, dietary needs)
      then: the assistant cross-checks `kitchen_get_production_summary` lead time and recommends cakes from `square_list_catalog` filtered by halal/dietary tags
    - id: w3.ac5
      given: brief §3 "complaint handling" + brandbook §6 "Put out the fire first, find the cause second"
      when: a customer expresses dissatisfaction
      then: the assistant apologises on behalf of HappyCake, offers a remedy path, and creates a Telegram escalation to the owner — never argues, never blames the customer
    - id: w3.ac6
      given: brief §3 "order status question"
      when: a customer asks about an existing order
      then: the assistant looks up by order id (or contact + recent date) via Square/POS tools and reports the current status — or, if not found, says "I don't have that order on file" without inventing
    - id: w3.ac7
      given: brief §3 "escalation to owner"
      when: a question exceeds assistant capability (custom decoration, complaint, refund, off-menu request)
      then: the assistant posts a structured handoff to the owner's Telegram bot AND tells the customer "the HappyCake team will be in touch within the hour" (matches brandbook §6 acknowledgment rule)
    - id: w3.ac8
      given: brand.r9 (kitchen-capacity precondition)
      when: the assistant answers any availability or timing question
      then: a `kitchen_get_production_summary` call is logged in `mcp_audit_log` immediately preceding the reply
    - id: w3.ac9
      given: brandbook §2 closing pattern + §6 "We answer in the channel we were asked"
      when: the assistant ends any reply with a CTA
      then: it uses the closing pattern "Order on the site at happycake.us or send a message on WhatsApp." (or the channel-appropriate equivalent on the site itself) (covers brand.r8)
    - id: w3.ac10
      given: brand.r1 (English only)
      when: a customer writes in Russian, Spanish, Kazakh, or any non-English language
      then: the assistant replies in English and offers human handoff if the customer struggles
    - id: w3.ac11
      given: brandbook §2 wordmark + cake-name rules
      when: the assistant references the brand or any cake
      then: "HappyCake" is spelled correctly and cake names appear as `cake "Honey"`, `cake "Napoleon"`, etc. (covers brand.r2 + brand.r3)
  edge_cases:
    - id: w3.ec1
      given: MCP tool times out
      when: the assistant needs catalog or kitchen data
      then: it retries (per src/core/retry.py) and on persistent failure says "I can't reach our system right now — let me get a teammate" and escalates
    - id: w3.ec2
      given: customer asks for a flavor not in catalog
      when: the assistant must respond
      then: it says the flavor is not on the menu and lists what is available; it never claims the missing flavor exists (brand.r5)
    - id: w3.ec3
      given: customer is verbally abusive
      when: the assistant must respond
      then: it remains polite, does not engage, escalates to owner, and continues to follow brand voice
    - id: w3.ec4
      given: customer asks "are you human?"
      when: the assistant must respond
      then: it answers honestly that it is the HappyCake assistant and offers the human team for any concern
  data_dependencies:
    - square_list_catalog (read, every product Q)
    - square_create_order (write, only on confirmed intent)
    - kitchen_get_production_summary (read, every availability Q)
    - kitchen_create_ticket (write, on confirmed order)
    - Telegram bot (escalation channel)
  out_of_scope:
    - voice or video chat (text-only widget per brief silence)
    - in-widget payment (brief §4 disallows real payment credentials)
    - persistent multi-session memory across devices (sandbox is single-tenant; session-only state acceptable)
    # AMBIGUOUS: brief §3 "complaint handling" vs brandbook §6 "for emotional customers, give them time. Acknowledge the issue, ask for their phone number for a call" — interpretation A: ALWAYS escalate to owner. Interpretation B: only when emotion threshold crossed. Default A: every complaint generates a Telegram escalation, owner decides next step.
```

---

## w4 — WhatsApp

```yaml
workflow:
  id: w4
  name: WhatsApp inquiry-to-order pipeline
  goal: "Answer WhatsApp messages quickly in HappyCake voice and convert qualified inquiries into kitchen-ready order tickets with owner-visible handoff."
  primary_actor: Customer
  channel: WhatsApp (simulated via world_next_event → webhook → bot)
  inputs:
    - name: inbound WhatsApp message
      type: { from, text, attachments?, timestamp }
      source: world_next_event simulating WhatsApp lead, OR webhook on tunnel URL
    - name: customer profile
      type: phone, name (when known)
      source: WhatsApp message metadata
    - name: catalog
      type: product list
      source: square_list_catalog
    - name: kitchen state
      type: production summary
      source: kitchen_get_production_summary
    - name: order intent
      type: structured fields after qualification
      source: agent extraction from conversation
  acceptance_criteria:
    - id: w4.ac1
      given: brief §3 "WhatsApp should answer quickly and in brand voice"
      when: an inbound WhatsApp message arrives
      then: a reply is dispatched within 2 seconds (ack first, work async — per repo CLAUDE.md Telegram conventions, applied to outbound channels) AND the reply matches brand voice rules
    - id: w4.ac2
      given: brief §3 useful scenario "menu questions"
      when: a customer asks about cakes/flavors/prices
      then: the reply is sourced from `square_list_catalog`, names cakes correctly (`cake "Honey"`, etc.), and quotes specific price+weight (covers brand.r12)
    - id: w4.ac3
      given: brief §3 "date availability"
      when: a customer asks if a cake can be ready by date X
      then: `kitchen_get_production_summary` is called BEFORE the answer (brand.r9) and the reply either confirms with the lead-time math or proposes a feasible alternative
    - id: w4.ac4
      given: brief §3 "custom cake request"
      when: a customer asks for a custom cake
      then: the assistant captures details and escalates to owner Telegram with full context — does not promise delivery in-channel until owner approves
    - id: w4.ac5
      given: brief §3 "order intake"
      when: a customer confirms an order
      then: a `kitchen_create_ticket` is created with idempotency key (per CLAUDE.md project-wide "Idempotency for side effects") and a `square_create_order` is recorded; both call IDs are logged
    - id: w4.ac6
      given: brief §3 "human handoff"
      when: the conversation requires owner attention (custom, complaint, refund, off-menu, ambiguous)
      then: the bot posts the full thread + extracted intent to the owner's Telegram bot
    - id: w4.ac7
      given: brief §3 "kitchen/cashier note"
      when: an order is accepted
      then: the kitchen ticket includes pickup/delivery time, item list with sizes, customer contact, and any allergen/halal flags
    - id: w4.ac8
      given: brand.r1 (English only)
      when: a customer writes in another language
      then: the reply is in English, optionally offering human handoff
    - id: w4.ac9
      given: brand.r8 + brandbook §2 "Match the channel. WhatsApp replies are shorter and faster"
      when: the assistant closes a WhatsApp reply
      then: it uses the closing pattern in concise WhatsApp-appropriate form
    - id: w4.ac10
      given: brand.r5 (no fabrication) + brand.r9 (kitchen precondition)
      when: any answer touches price, ingredient, hours, availability, or lead time
      then: the corresponding MCP call appears in `mcp_audit_log` immediately before the outbound message
    - id: w4.ac11
      given: brandbook §6 community management "First word is a greeting" + "Address by name when known"
      when: the bot opens any WhatsApp reply
      then: it greets and uses the customer's name when available from profile metadata
  edge_cases:
    - id: w4.ec1
      given: a customer sends only an emoji or sticker
      when: the bot processes the message
      then: it replies with a polite friendly opener and asks one clarifying question (no fabricated reply)
    - id: w4.ec2
      given: a customer sends a photo of a competitor cake and asks "can you make this?"
      when: the bot processes the message
      then: it acknowledges, captures the image reference, escalates to owner (per w3.ac3 — custom requests escalate)
    - id: w4.ec3
      given: kitchen capacity is full
      when: a customer requests a same-day order
      then: the bot offers the next available date from `kitchen_get_production_summary`, never silently accepts
    - id: w4.ec4
      given: the customer cancels mid-conversation
      when: a draft order ticket exists in flight
      then: no `kitchen_create_ticket` or `square_create_order` is finalised; if already created, a cancellation/void path is invoked
  data_dependencies:
    - world_next_event (read, polls simulated WhatsApp events)
    - square_list_catalog (read)
    - square_create_order (write, idempotency key)
    - kitchen_get_production_summary (read)
    - kitchen_create_ticket (write, idempotency key)
    - Telegram bot (owner escalation)
  out_of_scope:
    - real WhatsApp Business API credentials (brief §4)
    - voice notes / WhatsApp calls (brief silent)
    - group chat handling (brief silent)
    - multi-language replies (brand.r1)
```

---

## w5 — Instagram

```yaml
workflow:
  id: w5
  name: Instagram as a sales channel
  goal: "Turn Instagram presence into a sales loop: brand-voice posts (with owner approval), comment replies, DM order capture, and routing into an order path."
  primary_actor: Customer (DMs/comments) AND Owner (post approvals)
  channel: Instagram (simulated; DMs + comments + post drafts; world_next_event drives traffic)
  inputs:
    - name: inbound DM
      type: { from, text, attachments?, timestamp }
      source: world_next_event simulating Instagram DM
    - name: inbound comment
      type: { post_id, from, text }
      source: world_next_event simulating Instagram comment
    - name: post draft request
      type: trigger (scheduled or owner-initiated) + content group
      source: scheduler / owner Telegram command
    - name: photo assets
      type: 22 optimized images
      source: /hackathon-assets/happy-cake/
    - name: brand voice
      type: agent persona
      source: agent/*.md
    - name: owner approval decision
      type: Approve / Edit / Reject (with optional edit text)
      source: Telegram inline keyboard on draft preview
  acceptance_criteria:
    - id: w5.ac1
      given: brief §3 "content plan"
      when: the system is asked to produce a weekly Instagram plan
      then: the plan follows brandbook §5 cadence (Mon 10:00 Product, Tue 14:00 Audience, Wed 10:00 Product, Thu 14:00 Company, Fri 10:00 Product, Sat 11:00 Audience, Sun 12:00 Product) and respects content-group rules (one group per post)
    - id: w5.ac2
      given: brief §3 "post/story ideas" + brand.r6 (no publishing without approval)
      when: a post draft is generated
      then: it is sent to the owner's Telegram with Approve / Edit / Reject inline keyboard (gap-fix #2) and is NOT published until the owner taps Approve
    - id: w5.ac3
      given: brief §3 "replies to comments" + brandbook §6 "We answer in the channel we were asked"
      when: a comment arrives on a post
      then: the bot drafts a reply in brand voice and posts it as a comment reply (replies to comments do not require approval per brandbook §7 approval-flow note: "Replies to comments and DMs do not need approval. They need to follow this brand book.")
    - id: w5.ac4
      given: brief §3 "DM order capture"
      when: a DM expresses purchase intent
      then: the bot qualifies (item, size, date, contact), calls `square_list_catalog` + `kitchen_get_production_summary`, and creates `kitchen_create_ticket` + `square_create_order` with idempotency keys
    - id: w5.ac5
      given: brief §3 "routing interested customers into an order path"
      when: a customer expresses interest in DM
      then: the bot includes the closing pattern (brand.r8) directing them to the site or WhatsApp
    - id: w5.ac6
      given: brief §3 "using photo assets and brand voice correctly" + brandbook §4 photo style 50% products / 25% process / 10% interior+city / 10% text / 5% other
      when: a post draft is assembled
      then: the chosen image comes from the approved asset pack (no AI-generated cake imagery), and the proportion across the weekly plan respects the percentages
    - id: w5.ac7
      given: brand.r4 (≤3 emoji)
      when: a post or reply is composed
      then: emoji count ≤3, often 0; never in price lists or menus (brandbook §2 editorial rule 5)
    - id: w5.ac8
      given: brandbook §6 "Never delete a customer comment, on any channel" (= brand.r7)
      when: a comment is negative, critical, or contains a complaint
      then: the bot never invokes a delete operation; instead drafts a public reply per brandbook §6 negativity examples
    - id: w5.ac9
      given: brandbook §2 closing pattern (brand.r8)
      when: a post is published
      then: the body ends with "Order on the site at happycake.us or send a message on WhatsApp."
    - id: w5.ac10
      given: brandbook §6 "We sign as people. *the HappyCake team* or, for a personal touch, *Saule*"
      when: a DM or comment reply is sent
      then: it is signed as `— the HappyCake team` or a named person, never `Administration` or `Management`
    - id: w5.ac11
      given: brandbook Appendix B "Days we do not celebrate publicly"
      when: a content plan is generated
      then: it does not produce posts for marketing-invented days (e.g., National Donut Day)
  edge_cases:
    - id: w5.ec1
      given: owner taps "Edit" on a draft
      when: the owner sends edit text back
      then: the bot revises the draft and re-queues it for approval (gap-fix #2 flow)
    - id: w5.ec2
      given: owner taps "Reject"
      when: the rejection arrives
      then: the bot does not publish, files the reason, and does not retry the same draft
    - id: w5.ec3
      given: a comment is in a non-English language
      when: the bot drafts a reply
      then: the reply is in English (brand.r1)
    - id: w5.ec4
      given: a DM contains personally-identifying info (phone, address) the customer wants kept private
      when: the bot creates a kitchen ticket
      then: the ticket persists the data only inside the sandbox state, not in any public-facing post or reply
  data_dependencies:
    - world_next_event (read, polls simulated Instagram events)
    - square_list_catalog (read)
    - square_create_order (write)
    - kitchen_get_production_summary (read)
    - kitchen_create_ticket (write)
    - Telegram bot (approval queue, owner escalations)
    - asset pack `/hackathon-assets/happy-cake/`
  out_of_scope:
    - real Instagram Graph API credentials (brief §4)
    - story creation / publishing (brief §3 lists "post/story ideas" — interpreted as draft generation, not actual story API)
    - automated influencer outreach (brief silent; default no)
    - boosting/promoting posts directly from IG (those go through w6)
    # AMBIGUOUS: brief §3 "DM order capture" vs brandbook §7 "Replies to comments and DMs do not need approval" — interpretation A: DM replies skip approval but order-creation side effects always go through `kitchen_create_ticket` (which IS visible to owner via Telegram notification). Interpretation B: any monetary action requires approval. Default A.
```

---

## w6 — Marketing $500/month plan

```yaml
workflow:
  id: w6
  name: Marketing $500/month closed-loop plan
  goal: "Make a $500/month budget perform like $5,000 across Meta Ads, Google Ads, boosted posts, local search, organic content, review generation, and follow-up — with margin/AOV math and attribution back to orders."
  primary_actor: Owner
  channel: Telegram (owner) + Marketing simulator (MCP) + landing pages (w1)
  inputs:
    - name: budget envelope
      type: $500 USD/month
      source: brief §3 / §3.6 (fixed)
    - name: catalog with margins
      type: product list with cost basis (where available)
      source: square_list_catalog (read)
    - name: POS history
      type: order history, AOV, conversion data
      source: square_get_pos_summary (read)
    - name: campaign creation request
      type: { name, channel, budget, audience, creative, attribution }
      source: agent decision based on plan
    - name: simulated lead generation
      type: leads with attribution
      source: marketing_generate_leads (read in simulation)
    - name: owner approval
      type: Approve / Edit / Reject for each campaign
      source: Telegram inline keyboard
    - name: attribution from web/landing
      type: utm_source, utm_campaign, lead-form submissions
      source: w1 landing pages
  acceptance_criteria:
    - id: w6.ac1
      given: brief §3 "make $500 work as hard as possible"
      when: a marketing plan is produced
      then: it is delivered as `docs/MARKETING_PLAN.md` AND the plan splits the $500 across at least four of the listed channels (Meta Ads, Google Ads, boosted posts, local search, organic content, review generation, follow-up and repeat orders) — with a USD allocation per channel summing to ≤ $500
    - id: w6.ac2
      given: brief §3 "Use margin, order value, conversion assumptions, and local-customer logic. Do not write generic marketing advice."
      when: the plan is reviewed
      then: every channel allocation includes (a) assumed margin %, (b) assumed AOV, (c) assumed conversion rate, (d) one Sugar Land-specific local insight (median income $110K, multicultural, etc., per brandbook §3) — not generic copy
    - id: w6.ac3
      given: sandbox pack "Start your demand engine with `marketing_create_campaign`, then launch, generate leads, route them, adjust, and report back to the owner"
      when: the system runs through the marketing flow
      then: at least one real campaign is created via `marketing_create_campaign`, launched via `marketing_launch_simulated_campaign`, leads generated via `marketing_generate_leads`, and reported to owner via `marketing_report_to_owner`
    - id: w6.ac4
      given: gap-fix #4 "Marketing attribution loop"
      when: a lead form on a w1 landing page is submitted
      then: the lead persists `utm_source` + `utm_campaign` and `marketing_report_to_owner` is called with the attribution payload
    - id: w6.ac5
      given: brand.r6 (no publishing without approval) + brandbook §7 "Every post and every paid-ads creative goes through this approval flow"
      when: a paid-ads creative draft is generated
      then: the creative is sent to the owner's Telegram for Approve / Edit / Reject before any campaign launch
    - id: w6.ac6
      given: PLAN.md outcome 6 "/budget Telegram command"
      when: the owner sends `/budget` to the Telegram bot
      then: the bot returns the current allocation, spend-to-date (from simulator state), and the next planned action
    - id: w6.ac7
      given: brief §3 "review generation"
      when: the plan addresses reviews
      then: it specifies how Google Business reviews will be solicited (brandbook §5 "Google Business: 2–3 posts/week, every review answered") with concrete steps, not generic advice
    - id: w6.ac8
      given: brief §3 "follow-up and repeat orders"
      when: the plan addresses retention
      then: it defines a follow-up trigger (e.g., 30 days after order) using customer contact captured via WhatsApp/IG/site forms, respecting "permission-based contact" (brandbook §3 customer journey stage 6)
    - id: w6.ac9
      given: brand.r10 voice tone scale + brandbook §5 "Avoid trend-chasing memes that don't fit our voice"
      when: any creative copy is generated
      then: it follows the post structure (Hook / Body / CTA / Static block / Hashtags), 600–1,000 chars, ≤3 emoji, closes with brand.r8
    - id: w6.ac10
      given: sandbox pack "Score marketing as a closed loop: plan, launch simulation, leads, conversion, metrics, adjustment"
      when: a campaign has run for the simulated period
      then: the system reports ROAS or CPA back to the owner via Telegram + `marketing_report_to_owner` and recommends one adjustment for the next cycle
    - id: w6.ac11
      given: brandbook Appendix B "Mother's Day, Thanksgiving, Christmas" listed as paid-ads peaks
      when: the calendar contains a relevant peak
      then: the plan increases allocation toward that peak window with rationale tied to the brandbook calendar
  edge_cases:
    - id: w6.ec1
      given: cumulative campaign spend would exceed $500
      when: the next launch is attempted
      then: the system blocks the launch and posts a Telegram message asking the owner whether to reallocate or pause
    - id: w6.ec2
      given: a campaign produces zero leads after the simulated period
      when: the next plan iteration runs
      then: the plan pauses or kills that channel and reallocates the remaining budget, with explanation in Telegram
    - id: w6.ec3
      given: an ad creative draft contains banned wording (e.g., "Buy now! Limited offer!" — brandbook §2 example)
      when: the brand-voice linter (`src/core/voice.py`) runs
      then: the draft is flagged and re-generated before reaching the approval queue
    - id: w6.ec4
      given: the `marketing_create_campaign` call fails with a server error
      when: retried
      then: the same idempotency key is used so a successful retry does not double-create
  data_dependencies:
    - marketing_create_campaign (write)
    - marketing_launch_simulated_campaign (write)
    - marketing_generate_leads (read in simulation)
    - marketing_report_to_owner (write)
    - square_list_catalog (read, margins)
    - square_get_pos_summary (read, AOV / sales)
    - evaluator_get_evidence_summary (read, for ROAS verification)
    - Telegram bot (/budget command, approval queue)
  out_of_scope:
    - real Meta or Google Ads spend (brief §4 — no real credentials)
    - email marketing (brandbook §5 marks email as future, opt-in only — default not in MVP)
    - SMS blasts (brief silent; brandbook silent on SMS)
    - influencer contracts / negotiations
    - dynamic personalization beyond utm_source/utm_campaign
    # AMBIGUOUS: brief §3 "Use margin, order value, conversion assumptions, and local-customer logic" — interpretation A: hardcoded reasonable assumptions documented in MARKETING_PLAN.md. Interpretation B: derive from `square_get_pos_summary` at runtime. Default B where data is available; A with explicit "assumed" labels otherwise.
```

---

## Brandbook hard-rule coverage matrix

Every brandbook §7 hard rule is enforced in at least one workflow's acceptance_criteria.

| Brand rule | Enforced in |
|---|---|
| brand.r1 (English only) | w3.ac10, w4.ac8, w5.ec3 |
| brand.r2 (HappyCake wordmark) | w1.ac6, w3.ac11 |
| brand.r3 (cake names in quotes) | w1.ec3, w3.ac11, w4.ac2 |
| brand.r4 (≤3 emoji) | w5.ac7 |
| brand.r5 (no fabrication) | w1.ec1, w3.ac1, w3.ec2, w4.ac10 |
| brand.r6 (no publishing without approval) | w5.ac2, w6.ac5 |
| brand.r7 (never delete a customer comment) | w5.ac8 |
| brand.r8 (closing pattern) | w1.ac7, w3.ac9, w4.ac9, w5.ac9, w6.ac9 |
| brand.r9 (kitchen-capacity precondition) | w1.ac3, w3.ac8, w4.ac3, w4.ac10 |
| brand.r10 (voice tone scale) | w6.ac9 |
| brand.r11 (no abbreviations) | (linter scope; not asserted per workflow — see open questions) |
| brand.r12 (specific quantities) | w1.ac10, w4.ac2 |

---

## Open questions for Planner

These are constraints I could not place cleanly into a single workflow block. Planner should resolve:

1. **brand.r11 (no abbreviations except standard units)** is currently only in the cross-cutting matrix; it is enforced by the brand-voice linter. If the Tester wants per-workflow assertions, add `wN.acN` rows for each customer-facing workflow.
2. **Telegram owner-side workflows** (e.g., `/dashboard`, order-notification handler from PLAN.md Phase 2b) are not a brief §3 "outcome" but are required for w3/w4/w5/w6 escalation and approval to function. Decide whether to add a separate `w0` (or `w7` "Owner Telegram") block, or fold it into each workflow's data_dependencies as is currently done.
3. **`world_advance_time`** is a destructive integration-test tool listed by sandbox; the brief does not bind a customer-facing behavior to it. Currently treated as test infrastructure (not in any workflow's data_dependencies). Confirm.
4. **`evaluator_score_world_scenario` / `evaluator_generate_team_report`** — used to self-grade and to generate the submission report. Not customer-facing. Confirm whether to add a `w7` ("Evaluator self-scoring & submission evidence") block.
5. **AMBIGUOUS tags** in w2, w3, w5, w6 above need a Planner pick.
6. **Brief §3 "On-site assistant" mentions "It should not invent facts"** — covered by w3.ac1 broadly, but does the Tester want a specific negative test ("ask for non-existent product, assert non-fabrication")? Currently captured in w3.ec2.
7. **Brief §4 runtime rules (Claude Code CLI only, no SDK, etc.)** are infrastructure constraints, not customer-visible behavior. They are out of scope for `specs.md` and live in `docs/PLAN.md` locked decisions instead.
