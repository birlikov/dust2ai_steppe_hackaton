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
    id: "sq_item_pistachio_roll",
    variationId: "sq_var_pistachio_roll",
    kitchenProductId: "pistachio-roll",
    slug: "pistachio-roll",
    name: 'cake "Pistachio Roll"',
    category: "classics",
    priceUsd: 44.0,
    priceFormatted: "$44.00",
    weightLabel: "1.0 kg",
    leadTimeMinutes: 1440,
    halal: null,
    description:
      "Light meringue, butter cream, the sour-sweet of fresh raspberry.",
    image: "/brand/products/happy-cake-product-03.webp",
  },
];

const STATIC_FALLBACK: CatalogResponse = {
  products: FALLBACK_PRODUCTS,
  kitchen: { remainingCapacityMinutes: 420, overCapacity: false },
  source: "static_fallback",
  fetchedAt: new Date().toISOString(),
};

export const GET: APIRoute = async () => {
  const catalog = (await fetchCatalog()) ?? STATIC_FALLBACK;

  return new Response(JSON.stringify(catalog, null, 2), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
    },
  });
};
