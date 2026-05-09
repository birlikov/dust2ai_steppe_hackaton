# Web ↔ Backend API contracts

> Stable contracts the storefront (`web/`, Astro) and the agent backend (`src/webhooks`)
> agree on. Both sides build to this file. The backend serves these endpoints from a
> single FastAPI app (`src.webhooks.app:app`) on `http://localhost:8000` in dev.
> Production swaps `localhost:8000` for the public ngrok URL.

## CORS / origins

The backend allows requests from `http://localhost:4321` (Astro dev), the deploy
domain (`https://happycake.us` once live), and the ngrok URL. Requests from anywhere
else are rejected. The backend reads the allowlist from the `WEB_ALLOWED_ORIGINS`
env var (comma-separated; defaults to `http://localhost:4321`).

## Endpoints

### `GET /health`
Liveness probe. Returns `{"status": "ok"}`. Already implemented.

### `GET /api/catalog`
Returns the product catalog as JSON, sourced from `square_list_catalog` MCP. The
website renders `/cake/[slug]` from this; an external agent can read it directly to
shop the site programmatically (covers w2.ac2 — agent-friendly catalog).

**Response 200**:
```json
{
  "products": [
    {
      "id": "sq_item_honey_cake_slice",
      "variationId": "sq_var_honey_cake_slice",
      "kitchenProductId": "honey-cake-slice",
      "slug": "honey-cake-slice",
      "name": "cake \"Honey\" — slice",
      "category": "slices",
      "priceUsd": 8.50,
      "priceFormatted": "$8.50",
      "weightLabel": null,
      "leadTimeMinutes": 5,
      "halal": null,
      "description": "Individual honey cake slice for walk-ins and quick pickup.",
      "image": "/assets/brand/products/happy-cake-product-01.webp"
    }
  ],
  "kitchen": {
    "remainingCapacityMinutes": 420,
    "overCapacity": false
  },
  "source": "happycake_mcp",
  "fetchedAt": "2026-05-09T12:00:00Z"
}
```

The mapping from raw `square_list_catalog` items to this shape is owned by the
backend (see `src/webhooks/storefront.py`). The frontend never calls the MCP server
directly. Slugs are derived from `name` (kebab-cased, "cake " prefix stripped). Cake
names in the `name` field follow the brandbook pattern (`cake "Honey" — slice`,
`cake "Napoleon"`) so the frontend can echo them as-is.

**Response 503**: when the MCP catalog fetch fails after the retry budget is
exhausted (covers w1.ec1 / w2.ec1):
```json
{"error": "catalog_unavailable", "message": "We're updating the menu — try again in a moment."}
```

### `GET /api/policies`
Returns the human-readable policy text the website renders at `/policies`. Static
text owned by `src/webhooks/storefront.py`. Lets agents discover policies without
scraping (covers w2.ac3).

**Response 200**:
```json
{
  "sections": [
    {"id": "pickup", "title": "Pickup", "body": "..."},
    {"id": "delivery", "title": "Delivery", "body": "..."},
    {"id": "lead_times", "title": "Lead times", "body": "..."},
    {"id": "refunds", "title": "Refunds", "body": "..."},
    {"id": "allergens", "title": "Allergens", "body": "..."},
    {"id": "halal", "title": "Halal", "body": "..."}
  ],
  "version": 1
}
```

### `POST /api/chat`
The on-site assistant chat widget posts here. The backend invokes `ClaudeBridge`
with the composed runtime persona, returns the text reply, and persists the turn
in the session store + audit log. Channel is recorded as `website`.

**Request**:
```json
{
  "session_id": "optional-uuid-from-prior-turn",
  "message": "hi, do you have honey cake today?",
  "history": []  // optional; backend may reload from session_id
}
```

The backend creates or retrieves a session keyed by (channel="website",
external_id=session_id-or-fresh-uuid). If the request omits `session_id`, the
backend mints one and returns it; the frontend persists it in `localStorage` for
the rest of the visit.

**Response 200**:
```json
{
  "session_id": "uuid",
  "reply": "yes — the cake \"Honey\" is on the counter today, 1.2 kg, $42. Order on the site at happycake.us or send a message on WhatsApp.",
  "voice_warnings": []
}
```

`voice_warnings` is the brand-voice linter output (empty if the reply is clean).
The frontend ignores warnings in production but the backend logs them.

**Response 502**: when the bridge fails after retries.
```json
{"error": "model_unreachable", "message": "I couldn't reach the team's assistant just now — please try again in a moment."}
```

### `POST /api/lead`
Lead form on `/order` and `/custom`. Persists the lead with attribution and
notifies the owner via `marketing_report_to_owner`.

**Request**:
```json
{
  "name": "Maria",
  "contact": "+12815550100",
  "intent": "I'd like to order a cake \"Honey\" for Saturday",
  "channel_preference": "whatsapp",
  "utm_source": "instagram",
  "utm_campaign": "mothers_day_2026",
  "page": "/cake/honey-cake-slice"
}
```

**Response 200**:
```json
{"status": "received", "lead_id": "uuid"}
```

**Response 400**: missing required fields (`name`, `contact`, `intent`). Field-level
errors keyed by field name (covers w2.ec2).

### `GET /sitemap.xml` and `GET /robots.txt`
Served by the Astro site (not the backend). Sitemap lists `/`, `/cake/[slug]` per
catalog item, `/policies`, `/order`, `/custom`. `robots.txt` allows everything
except `/api/*`.

## Brand decisions for `web/`

These override anything in `assets/brand/metadata.json` — see HANDOFF + brandbook §4:

- **Palette tokens** (Tailwind config):
  - `happy-blue-900`: `#0E2A3C` — primary dark, page chrome, footer
  - `happy-blue-700`: `#1B4868` — logo blue, primary buttons
  - `happy-blue-500`: `#3B7BA8` — links, mid accents
  - `happy-blue-200`: `#BFD8E8` — light surfaces, badges
  - `cream-50`: `#FBF6E8` — page background
  - `cream-100`: `#F4ECD3` — card surfaces
  - `cream-200`: `#E9DBB4` — pattern dots on dark
  - `accent-coral`: `#E08066` — Mother's Day / love
  - `accent-green`: `#6E9D74` — spring / Eid / Easter
  - `text-primary`: `#1A1816`
  - `text-on-blue`: `#FBF6E8`
- **Type**: `Cormorant Garamond` (display) + `Inter` (body). Use Google Fonts.
- **Wordmark**: `HappyCake` (one word, two caps). Cake names in quotes
  *after* the word "cake" — `cake "Honey"`. Closing pattern on every page footer
  and product page CTA: `Order on the site at happycake.us or send a message on WhatsApp.`
- **Photos**: only files under `assets/brand/products/`, `assets/brand/hero/`,
  `assets/brand/social/`, `assets/brand/logo/`. Never AI-generated. Astro `import`
  the assets from `../assets/brand/...` so they're optimised by Astro Image.
- **Layout**: generous whitespace; centred heroes; left-aligned everything else;
  borders 0.5 px solid `happy-blue-900` at 20% opacity over cream; no drop shadows
  on product cards.

## Site map (Astro routes)

| Path | What |
|---|---|
| `/` | Hero, today's bake, featured cakes, brand story strip, content callouts, footer with closing pattern |
| `/cake/[slug]` | Per-cake page sourced from `/api/catalog`. JSON-LD Product + Offer. Order CTA → `/order?slug=…&qty=1`. |
| `/order` | Lead form; reads attribution from URL; POST `/api/lead`. |
| `/custom` | Custom-cake intake form; same backend endpoint, `intent: "custom"`. |
| `/policies` | Sections from `/api/policies` rendered server-side at build (or fetch + cache). |
| `/about` | Brand story / company group content (one of the brandbook content groups). |
| `/sitemap.xml` | Generated at build. |
| `/robots.txt` | Generated at build. |
| `/_chat-widget.js` (or in-page component) | Floating chat widget; POST `/api/chat`. |

## Versioning + breaking changes

This file is the contract. If the backend needs to change a response shape, bump
`version` (where present) and update this file in the same commit. The website
build tolerates additive changes (extra fields) silently; any field rename or
removal is a breaking change.
