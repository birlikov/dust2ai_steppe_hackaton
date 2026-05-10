/**
 * API client for the HappyCake backend.
 *
 * All runtime data comes from the Python FastAPI backend at PUBLIC_API_BASE.
 * Never hardcode prices, catalog data, or policies — fetch at build or request time.
 *
 * Fallback behaviour on backend unreachability:
 *   - catalog(): returns null (callers render "We're updating the menu")
 *   - policies(): returns null (callers render a generic fallback)
 */

// Empty string → relative URLs (same origin as the page). Set
// PUBLIC_API_BASE=http://localhost:8000 in web/.env when running Astro
// dev separately from the backend.
const API_BASE = import.meta.env.PUBLIC_API_BASE ?? "";

// ─── Response shapes ────────────────────────────────────────────────────────

export interface Product {
  id: string;
  variationId: string;
  kitchenProductId: string;
  slug: string;
  /** Full name following brandbook pattern, e.g. `cake "Honey" — slice` */
  name: string;
  category: string;
  priceUsd: number;
  priceFormatted: string;
  /** Weight in kg, e.g. 1.2. Null for slice items sold individually. */
  weightLabel: string | null;
  /** Lead time in minutes for kitchen production. */
  leadTimeMinutes: number;
  /** Halal-certified. Null means unknown. */
  halal: boolean | null;
  description: string;
  /** Relative path to product image, e.g. `/brand/products/happy-cake-product-01.webp` */
  image: string;
}

export interface KitchenState {
  remainingCapacityMinutes: number;
  overCapacity: boolean;
}

export interface CatalogResponse {
  products: Product[];
  kitchen: KitchenState;
  source: string;
  fetchedAt: string;
}

export interface PolicySection {
  id: string;
  title: string;
  body: string;
}

export interface PoliciesResponse {
  sections: PolicySection[];
  version: number;
}

export interface ChatRequest {
  session_id?: string;
  message: string;
  history?: Array<{ role: string; content: string }>;
}

export interface ChatResponse {
  session_id: string;
  reply: string;
  voice_warnings: string[];
}

export interface LeadRequest {
  name: string;
  contact: string;
  intent: string;
  channel_preference?: string;
  quantity?: number;
  pickup_or_delivery?: "pickup" | "delivery";
  pickup_date?: string;
  utm_source?: string;
  utm_campaign?: string;
  page?: string;
}

export interface LeadResponse {
  status: "received";
  lead_id: string;
}

export interface LeadErrorResponse {
  detail: Record<string, string>;
}

// ─── Client helpers ──────────────────────────────────────────────────────────

async function get<T>(path: string): Promise<T | null> {
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      headers: {
        Accept: "application/json",
        // ngrok-free.app shows an HTML interstitial on first browser visit
        // unless this header is present. Harmless on a custom domain.
        "ngrok-skip-browser-warning": "true",
      },
      // In static builds this runs at build time — allow a short timeout.
      signal: AbortSignal.timeout(8000),
    });
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

// ─── Public API ──────────────────────────────────────────────────────────────

/**
 * Fetch the full product catalog.
 *
 * Use when: rendering the homepage featured section or any product listing.
 * Returns null if the backend is unreachable — callers must handle this gracefully.
 */
export async function fetchCatalog(): Promise<CatalogResponse | null> {
  return get<CatalogResponse>("/api/catalog");
}

/**
 * Fetch a single product by slug.
 *
 * Use when: rendering `/cake/[slug]` — falls back to null if unavailable.
 * Do NOT use when you already have the full catalog in scope.
 */
export async function fetchProduct(slug: string): Promise<Product | null> {
  const catalog = await fetchCatalog();
  if (!catalog) return null;
  return catalog.products.find((p) => p.slug === slug) ?? null;
}

/**
 * Fetch policy sections for `/policies`.
 *
 * Returns null if the backend is unreachable.
 */
export async function fetchPolicies(): Promise<PoliciesResponse | null> {
  return get<PoliciesResponse>("/api/policies");
}

/**
 * Post a chat message to the on-site assistant.
 *
 * Use when: the chat widget sends a user message.
 * Returns null on 502 or network error — callers show the reachability error.
 */
export async function postChat(
  req: ChatRequest
): Promise<ChatResponse | null> {
  try {
    const res = await fetch(`${API_BASE}/api/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "ngrok-skip-browser-warning": "true",
      },
      body: JSON.stringify(req),
    });
    if (!res.ok) return null;
    return (await res.json()) as ChatResponse;
  } catch {
    return null;
  }
}

/**
 * Submit a lead form (order intent or custom cake inquiry).
 *
 * Use when: the visitor submits `/order` or `/custom` form.
 * Returns { ok: true, data } on success, { ok: false, errors } on 4xx.
 */
export async function submitLead(
  req: LeadRequest
): Promise<
  | { ok: true; data: LeadResponse }
  | { ok: false; errors: Record<string, string> }
> {
  try {
    const res = await fetch(`${API_BASE}/api/lead`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "ngrok-skip-browser-warning": "true",
      },
      body: JSON.stringify(req),
    });
    if (res.ok) {
      return { ok: true, data: (await res.json()) as LeadResponse };
    }
    if (res.status === 400) {
      const body = (await res.json()) as LeadErrorResponse;
      return { ok: false, errors: body.detail ?? {} };
    }
    return { ok: false, errors: { _: "Something went wrong. Please try again." } };
  } catch {
    return { ok: false, errors: { _: "Could not reach the server. Please try again." } };
  }
}
