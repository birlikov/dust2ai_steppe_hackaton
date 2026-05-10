# SKILLS — Composable owner-agent macros

These are end-to-end recipes the owner can trigger with one English
instruction. Each skill lists the **trigger phrases**, the **tool sequence**,
and what to **report back**. When the owner gives you the inputs the skill
needs, **run it**. Don't narrate the steps; execute and summarise the
outcome in 1-3 sentences.

If a skill needs a piece of input you don't have (budget, audience, list
of recipients), ask for **only that** in one short sentence — then run the
rest.

---

## skill: dashboard

**Trigger phrases**: *"dashboard"*, *"how are we today?"*, *"give me a
status"*, *"what's going on?"*

1. In parallel: `square_get_pos_summary`, `kitchen_get_production_summary`,
   `evaluator_get_evidence_summary`.
2. Reply with **four bullets** (≤ 1 short sentence each):
   - Sales: orders + revenue + channel mix
   - Kitchen: utilisation + what's queued
   - Pending: drafts waiting on approval (count)
   - Urgent: anything from the brand-rule escalation triggers, or "nothing urgent"

---

## skill: anything-urgent

**Trigger phrases**: *"anything urgent?"*, *"do you need me?"*, *"what
needs my attention?"*

1. Pull pending drafts (count from owner-bot SQLite).
2. Pull negative GB reviews via `gb_list_reviews` (rating ≤ 3).
3. Pull current `kitchen_get_capacity`.
4. Reply: 1 sentence per urgent item, max 3. If nothing → just say
   *"Nothing urgent."*

---

## skill: create-promotion

**Trigger phrases**: *"create a promotion"*, *"new campaign"*, *"launch a
[event] campaign"*, *"run a Google Ads / Meta / IG campaign for $N"*

Inputs the owner must give (ask in one sentence if missing — list
**only** what's missing):
- Channel — `instagram | google_local | whatsapp | website | mixed`
- Budget USD (must fit in remaining `marketing_get_budget` envelope)
- Audience or occasion — *"Sugar Land moms for Mother's Day"*
- Offer — short line like *"cake \"Honey\" 1.2 kg, $42 — order by Saturday"*

Once you have all four, **run without further confirmation**:

1. `marketing_get_budget` — confirm room.
2. `marketing_create_campaign` with the inputs. Returns `campaignId`.
3. `marketing_launch_simulated_campaign` with the campaignId.
4. Schedule three Instagram drafts via `instagram_schedule_post`
   (Product / Audience / Company per brandbook §5 cadence) — but compose
   captions yourself; do not mention internal campaign IDs in the captions.
5. `marketing_report_to_owner` — files the report in the simulator.

**Report back**: *"Campaign ‘Mother's Day Meta’ is live with $80. Three IG
drafts are in your /inbox queue. I'll watch metrics and ping you if
performance lags."* No IDs. No JSON.

---

## skill: audit-pending

**Trigger phrases**: *"what's pending?"*, *"audit pending"*, *"show me
queues"*

1. Pending drafts (from SQLite via `/inbox` — count + by-channel
   breakdown).
2. Active campaigns: `marketing_get_campaign_metrics()` — list by name +
   one-line health.
3. Open kitchen tickets: `kitchen_list_tickets("pending")`.

Reply: 3 bullets. *"3 IG drafts pending, 2 GB review replies pending."*
*"2 campaigns live: Mother's Day Meta is healthy, Local Search is below
target."* *"5 kitchen tickets in flight; oldest 12 minutes."*

---

## skill: inventory-check

**Trigger phrases**: *"what's in stock?"*, *"inventory"*, *"are we out of
anything?"*

1. `square_list_catalog` — every variation id.
2. `square_get_inventory(variationIds=[...])` — bulk lookup.
3. Reply: one short line per product with the count.
   - *"Honey slices: 12. Pistachio roll: 6 — running low."*
   - Flag items below 10 units with *"running low"*; below 3 with *"about
     to run out — heads up."*

---

## skill: repeat-buyer-reactivation

**Trigger phrases**: *"reach out to repeat customers"*, *"reactivate"*,
*"DM customers from last month"*, *"send a reminder to past buyers"*

1. Pull recent orders: `square_recent_orders(limit=200)`.
2. Identify customers (by phone) who last ordered 30-90 days ago.
3. For each, draft a brand-voice WhatsApp reactivation message — tightly
   scoped, max 2 sentences, no banned adjectives, ends with the customer
   closing pattern.
4. **Do NOT call `whatsapp_send` directly.** File each as a draft in the
   approval queue (the bot's `drafts` table) — channel: `whatsapp`, kind:
   `reply`, payload contains `{to, message}`. The owner approves them via
   `/inbox`.
5. Report: *"Drafted 14 WhatsApp follow-ups for buyers who haven't ordered
   in 30+ days. They're in your /inbox queue."*

---

## skill: reply-to-reviews

**Trigger phrases**: *"reply to reviews"*, *"answer the bad review"*,
*"sweep Google reviews"*

1. `gb_list_reviews`.
2. For any review without a recorded reply (cross-check
   `gb_list_simulated_actions`), draft a brand-voice reply. Negative
   reviews follow brandbook §6 negativity examples — apologise on behalf
   of the team, offer a remedy, propose continuing on WhatsApp.
3. Call `gb_simulate_reply(reviewId, reply)` for each.
4. Report: *"Replied to 4 reviews. The 2-star one (rev_003) got an
   apology + WhatsApp follow-up offer."*

---

## skill: mothers-day-push

**Trigger phrases**: *"Mother's Day push"*, *"Mother's Day blast"*

A bundle: combine `create-promotion` (for the paid budget) + a Google
Business post draft + a WhatsApp blast template. Returns one consolidated
report instead of three separate ones.

1. Run `create-promotion` with channel=`instagram`, budget=$80 (or
   whatever the owner specified).
2. Draft a Google Business post: *"Mother's Day weekend — cake \"Honey\"
   on the counter all weekend."* Schedule via `gb_simulate_post` after
   owner approval (file as draft).
3. Draft a WhatsApp blast for opt-in customers — file as drafts, **never
   send directly without approval**.

Report: *"Mother's Day push staged: $80 IG campaign live, 1 GB post
draft, 12 WhatsApp drafts. All in /inbox."*

---

## How to invoke a skill

When you recognise a trigger phrase or close paraphrase, just **do the
skill**. You don't need to say *"I'll use the create-promotion skill"* —
that's dev-narration. Owners care about outcomes, not the mechanism.

If two skills could match (*"audit pending"* could be `audit-pending` or
`anything-urgent`), pick the one that better matches the owner's literal
words; if still ambiguous, ask in one sentence.

Skills can chain. *"Create a Mother's Day promotion and reach out to
repeat customers"* = `create-promotion` then
`repeat-buyer-reactivation`. Run them in order; report once at the end
with the outcomes of both.
