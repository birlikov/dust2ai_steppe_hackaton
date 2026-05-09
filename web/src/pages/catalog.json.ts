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
 * When the backend is unreachable (w2.ec1), returns an error JSON body.
 * Note: in static mode the HTTP status is always 200 from the file server;
 * the `error` field in the body signals unavailability to agent consumers.
 */
import type { APIRoute } from "astro";
import { fetchCatalog } from "../lib/api";

// Explicitly prerender (static output). Astro calls GET at build time.
export const prerender = true;

export const GET: APIRoute = async () => {
  const catalog = await fetchCatalog();

  if (!catalog) {
    // w2.ec1: backend unreachable — return structured error body
    return new Response(
      JSON.stringify({
        error: "catalog_unavailable",
        message: "We're updating the menu — try again in a moment.",
      }),
      {
        status: 200, // static files are always 200; agent reads the `error` field
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  // Expose the full catalog as agent-readable JSON
  return new Response(JSON.stringify(catalog, null, 2), {
    status: 200,
    headers: {
      "Content-Type": "application/json",
      "Cache-Control": "public, max-age=60, stale-while-revalidate=300",
    },
  });
};
