# Marketing plan — making $500/month perform like $5,000

> **The brief**: $500 monthly marketing budget; design a closed loop that
> reasons about margin, AOV, conversion, and Sugar Land local context to
> drive $5,000 in attributable revenue. Source data from
> `marketing_get_budget`, `marketing_get_sales_history`,
> `marketing_get_margin_by_product`, and `square_get_pos_summary`.
> Self-grade via `evaluator_score_marketing_loop`.

This plan is the canonical answer for **outcome 6** (workflow `w6` in
`docs/specs.md`). It's executed end-to-end by `scripts/seed_marketing.py`
and reported back to the owner via `marketing_report_to_owner` plus
`/budget` in the Telegram bot.

## 1. Sugar Land context (read once at plan boot)

- Sugar Land is a high-income (~$110K median household) suburb of Houston
  with a multicultural family base — Anglo, Hispanic, South Asian, East
  Asian, Central Asian diaspora.
- Customers buy for **personal celebrations** (birthdays, anniversaries,
  baby showers, gender-reveals), **calendar moments** (Mother's Day,
  Eid, Nauryz, Thanksgiving, Christmas), and **no-reason cakes** (Tuesday
  family dessert, office afternoons, gifts).
- The unifying customer trait: dessert is a small ritual, not a guilty
  treat. We don't compete with the bakery across town; we compete with
  the home kitchen.
- Calendar peaks (brandbook Appendix B): **Mother's Day weekend**
  (paid-ads peak), **Thanksgiving / Christmas**, smaller bumps on
  Father's Day, back-to-school, Valentine's Day, Nauryz.
- The diaspora segment is loyal-once-discovered — community word-of-mouth
  outperforms cold-channel ad spend per dollar.

## 2. Unit economics (sourced from MCP at runtime)

These are pulled from `marketing_get_margin_by_product` +
`marketing_get_sales_history` at plan boot. The numbers below reflect the
seeded sandbox at the time of writing; the script reads them live.

> Margin column below is from the seeded sandbox snapshot of
> `marketing_get_margin_by_product` (2026-05-09). The script reads it
> live; if the live numbers move, the table here may lag — re-run
> `scripts/seed_marketing.py` for the authoritative figures.

| Product | Price (USD) | Est. margin (snapshot 2026-05-09) | Notes |
|---|---|---|---|
| Honey cake slice (`honey-cake-slice`) | 8.50 | **68%** | Highest margin per dollar of ad spend; impulse-buy friendly |
| Pistachio roll (slice/roll) | (slices) 9.50 / (whole) 44 | 64-66% | Premium classic; pairs well with high-AOV upsell |
| Whole honey cake | 55 | 62% | Best for celebrations; AOV anchor |
| Office dessert box | 120 | 60% | Highest AOV; B2B angle |
| Custom birthday cake | 95 | 58% | Gated through owner approval; not a paid-ads target |

Historical baseline (`marketing_get_sales_history`): about **$18k/month
revenue** with **~700 orders** at **~$25 average ticket** — already
healthy. The $500 budget needs to add **$5,000 incremental revenue**, so
we need ~200 incremental orders, or ~50 incremental whole-cake orders.

**Implied break-even per channel**: at 65% blended margin, $500 spend
needs $769 incremental revenue *just to cover the spend*. The $5,000
target is ~10× spend; that's the bar.

## 3. Allocation — $500 across five channels

| # | Channel | Allocation | What it buys | Targeting / creative | Why this for HappyCake |
|---|---|---|---|---|---|
| 1 | **Meta Ads (Mother's Day weekend)** | $180 | 2 image ads on FB + IG, 3-day burst around the 2nd Sunday of May | Sugar Land 5-mile radius; women 25–55 with parental status; lookalike of past-12-month buyers. Creatives use approved photos from `assets/brand/social/` of cake "Honey" and cake "Milk Maiden". | Mother's Day is the brandbook-flagged peak. Meta's targeting is the only paid channel that can hit "moms within 10 minutes' drive" cleanly. |
| 2 | **Google Ads (local search)** | $120 | "cake delivery sugar land", "halal cake near me", "birthday cake same day Houston" | Exact + phrase match; ad extensions cite `happycake.us`, hours, address; sitelinks to `/cake/honey-cake-slice`, `/cake/pistachio-roll`, `/policies` | Google captures **demand-formation** customers — they already want a cake; we just need to be on the page. Brand-correct closing in description: *Order on the site at happycake.us or send a message on WhatsApp.* |
| 3 | **Boosted IG posts (organic→paid)** | $80 | $20/week × 4 weeks; boost the best-performing organic Product post (cake "Honey" + cake "Pistachio Roll" usually) | IG audience expansion within 10 mi. of Sugar Land; vertical IG-Reels-friendly aspect. | The brandbook's IG cadence already produces 5–7 posts/week; boosting the one that organically outperforms doubles the cheap reach without extra production. |
| 4 | **Local discovery — Google Business posts + reviews** | $40 | Tooling/credit for sending review-request follow-ups; small spend on a featured-business slot if available. Otherwise rolls into channel #2. | Reply to every review (`gb_simulate_reply`); 2–3 GB posts/week (`gb_simulate_post`). | The `gb_*` family is part of the scoring rubric and the brandbook §5 channel rules ("every review answered"). Review velocity → SEO → free traffic. |
| 5 | **Repeat / follow-up** | $80 | WhatsApp follow-up sequence: a 30-day "thinking of you" check-in on customers who placed an order via WhatsApp/IG; a "Tuesday cake" reminder for households we've sold to twice. | Permission-based (brandbook §3 stage 6); messages are short, brand-voice, no upsell pressure. | Repeat customers are the cheapest revenue HappyCake has — every $1 of follow-up generates more incremental revenue than $1 of cold acquisition. |
| | **Total** | **$500** | | | |

Each channel allocation includes a **planned conversion assumption** the
seed script writes into `marketing_create_campaign`'s `objective` field
so the evaluator can read it back:

| Channel | Assumed CTR | Assumed conversion | Implied orders | Implied revenue (at $25 AOV) |
|---|---|---|---|---|
| Meta Ads | 1.6% | 4.0% | ~57 orders | $1,425 |
| Google Ads (local intent) | 4.0% | 12.0% | ~52 orders | $1,300 |
| Boosted IG | 0.8% | 3.0% | ~30 orders | $750 |
| GB / discovery | n/a | review-driven | ~25 orders | $625 |
| Repeat / follow-up | 22% open, 8% reply | n/a (already a customer) | ~36 orders | $900 |
| **Total** | | | **~200 orders** | **~$5,000** |

That puts us at the $5,000 target with a deliberately conservative AOV
($25, the historical average — boosted by office-dessert-box and whole-
cake mixes the actual lift will be higher).

## 4. Creative principles (apply to every ad and post)

1. **One claim per creative.** *"Cake \"Honey\" — 1.2 kg, $42, ready
   through Sunday."* Not three.
2. **Real photos only.** From `assets/brand/{products,hero,social}/`. The
   brandbook forbids AI-generated cake imagery — we honour that even in
   paid ads.
3. **Closing pattern, verbatim.** *Order on the site at happycake.us or
   send a message on WhatsApp.*
4. **No banned adjectives.** *amazing / incredible / unbelievable / mouth-
   watering / the best* are off the list.
5. **≤3 emoji per creative.** Often zero.
6. **Cake names in quotes.** *cake "Honey"*, *cake "Napoleon"*. Never
   *Honey cake*.
7. **Owner approves every paid creative** (brand.r6) — drafts go through
   the `/inbox` Telegram queue.

### How the executable mirror covers each channel

`scripts/seed_marketing.py` is the **paid-spend** half of the plan; it
creates campaigns through `marketing_create_campaign` for **channels 1
and 2** ($180 Meta + $120 Google). Channels 3–5 are organic / non-paid
and run through different scripts:

| Channel | Executor | Tools fired |
|---|---|---|
| 1 — Meta Ads | `scripts/seed_marketing.py` | `marketing_create_campaign` + `launch` + `generate_leads` + `route_lead` + `adjust_campaign` + `report_to_owner` |
| 2 — Google Ads | `scripts/seed_marketing.py` | same as #1 |
| 3 — Boosted IG posts | `scripts/seed_drafts.py` (drafts → owner approval → `instagram_publish_post`) | `instagram_schedule_post` → `instagram_approve_post` → `instagram_publish_post` |
| 4 — GB / discovery | `scripts/seed_review_replies.py` (review-reply sweep) + future `gb_simulate_post` cadence | `gb_list_reviews` + `gb_simulate_reply` (per brandbook §5 "every review answered") |
| 5 — Repeat / follow-up | runtime persona during `WorldPoller` runs (`whatsapp_send` to past customers when permission is on file) | `whatsapp_send` |

The `evaluator_score_marketing_loop` rubric reads only the
`marketing_*`-tool evidence, so channels 1 and 2 are what move that
scorecard. Channels 3–5 contribute to `evaluator_score_channel_response`
(WA + IG + GB) and to brand-voice / agent-friendliness scoring.

## 5. Attribution loop

Every ad URL carries `?utm_source=…&utm_campaign=…`. The Astro storefront
forwards both into the lead form's hidden fields. The backend's
`/api/lead` endpoint persists them and calls `marketing_report_to_owner`
so the loop closes back to the owner without manual reconciliation.

The evaluator reads:

- `evaluator_get_evidence_summary` — campaign + lead + report counts
- `evaluator_score_marketing_loop` — the closed-loop score (0–100). The
  `gaps` array tells us exactly which step was skipped.

## 6. Adjustment cadence

After the simulated period for each campaign, the loop runs:

- `marketing_get_campaign_metrics(campaignId)`
- if CTR < target: rotate creative (new image from `assets/brand/social/`)
- if conversion < target: shorten the URL chain (deep-link to product
  page), check that the lead form pre-fills the slug
- if both are healthy and budget remains: **hold** — do not raise budget
  midstream beyond the planned envelope (gap-fix #6 honours the $500 cap)
- record adjustment via `marketing_adjust_campaign(campaignId,
  adjustment, expectedImpact)`
- summarise via `marketing_report_to_owner` with the next planned cycle

The Telegram `/budget` command surfaces the current state at any time.

## 7. What we deliberately don't do

- **No Meta or Google credentials in the repo.** All campaigns run
  through the `marketing_*` MCP tools (the simulator). The brief
  forbids real ad-platform credentials.
- **No SMS blasts.** Brandbook is silent on SMS; we don't have opt-in
  flows for it; the channel is not in scope.
- **No email marketing in the MVP.** The brandbook marks email as
  "future, opt-in only".
- **No National Donut Day / National Cake Day / etc.** Brandbook
  Appendix B explicitly excludes marketing-invented holidays.
- **No paid influencer outreach.** Sugar Land is small and trust-based;
  organic word-of-mouth + the diaspora segment outperforms paid posts.
- **No raising the $500 envelope mid-cycle.** If a channel is hot, we
  reallocate from a cold one (see §6); we never run over.

## 8. Calendar — what runs, when

| Week (May) | Channel #1 | Channel #2 | Channel #3 | Channel #4 | Channel #5 |
|---|---|---|---|---|---|
| W19 (May 4-10) | **Mother's Day burst** ($180) | always-on ($30) | boost Sat 11:00 Audience post ($20) | review-reply sweep ($10) | follow-up batch 1 ($20) |
| W20 (May 11-17) | — | always-on ($30) | boost Mon 10:00 Product post ($20) | GB post Wed ($10) | follow-up batch 2 ($20) |
| W21 (May 18-24) | — | always-on ($30) | boost Wed Product post ($20) | review-reply sweep ($10) | follow-up batch 3 ($20) |
| W22 (May 25-31) | — | always-on ($30) | boost Fri 10:00 Product post ($20) | GB featured slot ($10) | follow-up batch 4 ($20) |
| **Total** | $180 | $120 | $80 | $40 | $80 = **$500** |

Calendar shifts month-to-month with brandbook Appendix B peaks: June
keeps Father's Day light; July is a single greeting on Independence Day;
late November pivots Channel #1 to Thanksgiving; December swings hard to
Christmas. Any change requires owner approval through `/inbox` before
launch.

---

*Last updated 2026-05-09. Maintained alongside `scripts/seed_marketing.py`,
which is the executable form of this plan.*
