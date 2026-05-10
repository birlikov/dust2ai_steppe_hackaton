/**
 * /catalog.json — Machine-readable catalog endpoint.
 *
 * Covers w2.ac2: "a /catalog.json (or equivalent stable JSON endpoint) returns
 * the full product list with price, weight, lead_time, allergens, halal flag
 * derived from square_list_catalog".
 *
 * At build time (static output), this is called once and the response body
 * is written to dist/catalog.json.
 *
 * When the backend is unreachable, the response falls back to a curated
 * snapshot mirroring the seeded MCP catalog so an autonomous AI customer
 * always reads products, not an error envelope. The `source` field signals
 * whether the data is live ("happycake_mcp") or static ("static_fallback").
 */
import type { APIRoute } from "astro";
import { fetchCatalog } from "../lib/api";
import type { CatalogResponse, Product } from "../lib/api";

// Explicitly prerender (static output). Astro calls GET at build time.
export const prerender = true;

// Build-time API base for the prerender call only — see scripts/run.sh.
// PUBLIC_API_BASE stays "" in production so browser fetches use relative
// URLs (same origin as the page). HAPPYCAKE_BUILD_API_BASE is read here
// to point the *server-side* prerender at the local backend so this
// endpoint reflects live MCP data instead of the static_fallback shape.
const BUILD_API_BASE = (
  (typeof process !== "undefined" && process.env?.HAPPYCAKE_BUILD_API_BASE) ||
  ""
).replace(/\/$/, "");

async function fetchLiveCatalog(): Promise<CatalogResponse | null> {
  if (!BUILD_API_BASE) {
    return fetchCatalog();
  }
  try {
    const r = await fetch(`${BUILD_API_BASE}/api/catalog`, {
      headers: { Accept: "application/json" },
    });
    if (!r.ok) return null;
    return (await r.json()) as CatalogResponse;
  } catch {
    return null;
  }
}

const FALLBACK_PRODUCTS: Product[] = [
  {
    id: "sq_item_honey_cake_slice",
    variationId: "sq_var_honey_cake_slice",
    kitchenProductId: "honey-cake-slice",
    slug: "honey-cake-slice",
    name: 'cake "Honey" — slice',
    category: "slices",
    priceUsd: 8.5,
    priceFormatted: "$8.50",
    weightLabel: null,
    leadTimeMinutes: 5,
    halal: null,
    description: "Individual honey cake slice for walk-ins and quick pickup.",
    image: "/brand/products/happy-cake-product-01.webp",
  },
  {
    id: "sq_item_whole_honey_cake",
    variationId: "sq_var_whole_honey_cake",
    kitchenProductId: "whole-honey-cake",
    slug: "whole-honey-cake",
    name: 'cake "Honey" — whole',
    category: "whole-cakes",
    priceUsd: 55.0,
    priceFormatted: "$55.00",
    weightLabel: "1.2 kg",
    leadTimeMinutes: 1440,
    halal: null,
    description: "Classic whole honey cake for family orders.",
    image: "/brand/products/happy-cake-product-02.webp",
  },
  {
    id: "sq_item_pistachio_roll",
    variationId: "sq_var_pistachio_roll",
    kitchenProductId: "pistachio-roll",
    slug: "pistachio-roll",
    name: 'cake "Pistachio Roll"',
    category: "slices",
    priceUsd: 9.5,
    priceFormatted: "$9.50",
    weightLabel: null,
    leadTimeMinutes: 5,
    halal: null,
    description: "Premium pistachio roll dessert.",
    image: "/brand/products/happy-cake-product-03.webp",
  },
  {
    id: "sq_item_custom_birthday_cake",
    variationId: "sq_var_custom_birthday_cake",
    kitchenProductId: "custom-birthday-cake",
    slug: "custom-birthday-cake",
    name: 'custom cake "Birthday"',
    category: "custom",
    priceUsd: 95.0,
    priceFormatted: "$95.00",
    weightLabel: null,
    leadTimeMinutes: 1440,
    halal: null,
    description: "Custom celebration cake with human approval required.",
    image: "/brand/products/happy-cake-product-04.webp",
  },
  {
    id: "sq_item_office_dessert_box",
    variationId: "sq_var_office_dessert_box",
    kitchenProductId: "office-dessert-box",
    slug: "office-dessert-box",
    name: "office dessert box",
    category: "catering",
    priceUsd: 120.0,
    priceFormatted: "$120.00",
    weightLabel: "12 slices",
    leadTimeMinutes: 720,
    halal: null,
    description: "Assorted dessert box for offices and events.",
    image: "/brand/products/happy-cake-product-05.webp",
  },
];

const STATIC_FALLBACK: CatalogResponse = {
  products: FALLBACK_PRODUCTS,
  kitchen: { remainingCapacityMinutes: 420, overCapacity: false },
  source: "static_fallback",
  fetchedAt: new Date().toISOString(),
};

export const GET: APIRoute = async () => {
  const catalog = (await fetchLiveCatalog()) ?? STATIC_FALLBACK;

  return new Response(JSON.stringify(catalog, null, 2), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
    },
  });
};
