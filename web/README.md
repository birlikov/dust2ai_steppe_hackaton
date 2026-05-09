# HappyCake — Storefront (web/)

Astro 4 + Tailwind CSS storefront for happycake.us.  
Stack: Astro 4.x, Tailwind 3, TypeScript strict. No React. No additional frameworks.

## Prerequisites

- Node.js 18+
- npm 9+
- The Python backend running at `localhost:8000` (see `src/webhooks/` in the repo root).
  The site builds and serves without the backend, but the catalog and chat widget show
  graceful fallbacks instead of live data.

## Setup

```bash
cd web
cp .env.example .env        # set PUBLIC_API_BASE if backend is not at localhost:8000
npm install
npm run dev                 # starts Astro dev server at localhost:4321
```

Assets are copied from `../assets/brand/` into `public/brand/` automatically on dev/build.

## Commands

| Command | What it does |
|---|---|
| `npm run dev` | Copies brand assets, starts Astro dev server at `localhost:4321` |
| `npm run build` | Copies brand assets, builds static site to `dist/` |
| `npm run preview` | Serves the built `dist/` locally |
| `npm run lint` | TypeScript type-check only (no runtime errors) |

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `PUBLIC_API_BASE` | `http://localhost:8000` | Backend API base URL (Python uvicorn) |

Copy `.env.example` to `.env` and set the URL if deploying.

## Pages

| Route | Description |
|---|---|
| `/` | Homepage: hero, today's bake, featured cakes, brand story, callouts |
| `/cake/[slug]` | Per-product page with JSON-LD Product + Offer |
| `/order` | Lead form — POST `/api/lead`, UTM capture, field-level errors |
| `/custom` | Custom-cake intake form |
| `/policies` | Pickup, delivery, lead times, refunds, allergens, halal |
| `/about` | Brand story / Company content |
| `/guides/cake-for-x-guests` | Audience content guide |
| `/catalog.json` | Machine-readable catalog (agent-friendly, w2.ac2) |
| `/sitemap.xml` | Auto-generated sitemap |
| `/robots.txt` | Allow all, disallow /api/* |

## API contract

See `../docs/CONTRACTS.md` for the authoritative API contract this site builds against.

Endpoints used:
- `GET /api/catalog` — product catalog (fetched at build and runtime)
- `GET /api/policies` — policy sections
- `POST /api/chat` — on-site assistant chat widget
- `POST /api/lead` — order and custom-cake lead forms

## Brand assets

All images come from `../assets/brand/` (products, hero, social, logo).
The `npm run setup-assets` step copies them to `public/brand/`.
Never use AI-generated cake images.

## Chat widget

The floating bottom-right chat widget (`public/chat-widget.js`) is plain vanilla JS —
no framework dependency. It:
- Opens with "Good morning, friends. What can we help you with?"
- POSTs to `POST /api/chat` with a `session_id` persisted in `localStorage`
- Shows a typing indicator while waiting
- On 502/network error: "I couldn't reach the team's assistant just now — please try again in a moment."
- Is keyboard-accessible (Tab + Enter) with `aria-live="polite"` on the message log
