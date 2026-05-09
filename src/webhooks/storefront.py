"""Storefront helpers — shape MCP catalog + serve static policy text.

The website (``web/`` Astro project) reads ``/api/catalog`` and ``/api/policies``
through these helpers. Cake names are reformatted to the brandbook convention
(``cake "Honey"``) where possible. Photos are mapped to the curated asset pack
under ``assets/brand/products/``.

This module is import-safe (no I/O at import time). Routes call into it from
``src/webhooks/app.py``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

# Curated map of kitchen product ids to brand-correct display names. Keep
# in sync with the MCP catalog (one row per ``kitchenProductId``).
# Anything not in this map falls through to a heuristic that tries to invert
# "X cake" → ``cake "X"`` and logs nothing — the goal is best-effort, not
# perfection. The heuristic is good enough for the catalog the recon found.
KNOWN_CAKES: dict[str, str] = {
    "honey-cake-slice": 'cake "Honey" — slice',
    "whole-honey-cake": 'cake "Honey" — whole',
    "pistachio-roll": 'cake "Pistachio Roll"',
    "custom-birthday-cake": 'custom cake "Birthday"',
    "office-dessert-box": "office dessert box",
}

# Curated photo map — cycle through the product asset pack so each item gets
# a different image. Leftover items fall back to product-01.
PRODUCT_PHOTOS: dict[str, str] = {
    "honey-cake-slice": "/brand/products/happy-cake-product-01.webp",
    "whole-honey-cake": "/brand/products/happy-cake-product-02.webp",
    "pistachio-roll": "/brand/products/happy-cake-product-03.webp",
    "custom-birthday-cake": "/brand/products/happy-cake-product-04.webp",
    "office-dessert-box": "/brand/products/happy-cake-product-05.webp",
}
DEFAULT_PHOTO = "/brand/products/happy-cake-product-01.webp"


_RE_X_CAKE = re.compile(r"^(?P<name>[A-Za-z][\w ]*?) cake(?P<suffix>.*)$")


def slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return cleaned or "item"


def format_cake_name(raw: str, *, kitchen_product_id: str | None = None) -> str:
    """Return a brand-correct display name. Falls through to heuristic if unknown."""
    if kitchen_product_id and kitchen_product_id in KNOWN_CAKES:
        return KNOWN_CAKES[kitchen_product_id]
    m = _RE_X_CAKE.match(raw.strip())
    if m:
        name = m.group("name").strip().title()
        suffix = m.group("suffix").strip()
        if suffix:
            return f'cake "{name}" — {suffix}'.rstrip(" —")
        return f'cake "{name}"'
    return raw


def shape_catalog(
    raw: Mapping[str, Any] | None,
    *,
    kitchen: Mapping[str, Any] | None = None,
    fetched_at: datetime | None = None,
) -> dict[str, Any]:
    """Convert the MCP ``square_list_catalog`` payload to the contract shape."""
    products_in = []
    if raw and isinstance(raw, Mapping):
        catalog_field = raw.get("catalog")
        if isinstance(catalog_field, list):
            products_in = catalog_field

    products_out: list[dict[str, Any]] = []
    for item in products_in:
        if not isinstance(item, Mapping):
            continue
        kid = item.get("kitchenProductId")
        kid_str = kid if isinstance(kid, str) else None
        raw_name = item.get("name") or "item"
        display_name = format_cake_name(str(raw_name), kitchen_product_id=kid_str)
        slug = slugify(kid_str or str(raw_name))
        price_cents = item.get("priceCents")
        price_usd = (
            round(price_cents / 100, 2) if isinstance(price_cents, int) else None
        )
        products_out.append(
            {
                "id": item.get("id"),
                "variationId": item.get("variationId"),
                "kitchenProductId": kid_str,
                "slug": slug,
                "name": display_name,
                "name_raw": raw_name,
                "category": item.get("category"),
                "priceUsd": price_usd,
                "priceFormatted": (
                    f"${price_usd:,.2f}" if price_usd is not None else None
                ),
                "description": item.get("description"),
                "image": PRODUCT_PHOTOS.get(kid_str or "", DEFAULT_PHOTO),
            }
        )

    kitchen_block: dict[str, Any] = {}
    if isinstance(kitchen, Mapping):
        kitchen_block = {
            "remainingCapacityMinutes": kitchen.get("remainingCapacityMinutes"),
            "overCapacity": kitchen.get("overCapacity", False),
            "dailyCapacityMinutes": kitchen.get("dailyCapacityMinutes"),
        }

    return {
        "products": products_out,
        "kitchen": kitchen_block,
        "source": "happycake_mcp",
        "fetchedAt": (fetched_at or datetime.now(UTC)).isoformat(),
    }


# ---------------------------------------------------------------------------
# Static policy text — brandbook + brief-derived; in-tree so judges and agents
# can read it without scraping. Plain English, stable headings.
# ---------------------------------------------------------------------------

POLICIES_VERSION = 1

POLICY_SECTIONS: list[dict[str, str]] = [
    {
        "id": "pickup",
        "title": "Pickup",
        "body": (
            "Pickup is at HappyCake Sugar Land. Most items are ready within "
            "the same day; check the cake page for the lead time. We hold "
            "the cake on the counter for the time slot you pick — let us "
            "know on WhatsApp if you'll be later."
        ),
    },
    {
        "id": "delivery",
        "title": "Delivery",
        "body": (
            "Local delivery in Sugar Land and the closest Houston suburbs. "
            "We schedule delivery in 2-hour windows and notify you when we "
            "leave the kitchen. Delivery fees are calculated at checkout."
        ),
    },
    {
        "id": "lead_times",
        "title": "Lead times",
        "body": (
            "Slices and same-day classics: about 45 minutes from order to "
            "ready. Whole classics (cake \"Honey\", cake \"Napoleon\", cake "
            "\"Milk Maiden\", cake \"Pistachio Roll\", cake \"Tiramisu\"): "
            "ideally 24 hours so we bake to you, not from stock. "
            "Custom-decorated cakes need 24 hours minimum and are subject to "
            "the kitchen's daily custom capacity."
        ),
    },
    {
        "id": "refunds",
        "title": "Refunds",
        "body": (
            "If a cake is wrong or damaged when it reaches you, message us "
            "on WhatsApp within 24 hours and we'll make it right — same-day "
            "remake, replacement, or refund. We don't argue. The fix is on "
            "us."
        ),
    },
    {
        "id": "allergens",
        "title": "Allergens",
        "body": (
            "All cakes are made in a kitchen that handles wheat, eggs, "
            "dairy, and tree nuts (notably walnuts in the cake \"Honey\" and "
            "pistachios in the cake \"Pistachio Roll\"). Tell us about any "
            "allergy on the order form and we'll confirm what's safe before "
            "we bake."
        ),
    },
    {
        "id": "halal",
        "title": "Halal",
        "body": (
            "Most of the catalogue is halal-friendly — we'll mark each "
            "product on the page when we have a clean confirmation from the "
            "kitchen. The cake \"Tiramisu\" contains a small amount of "
            "cooking wine in the espresso syrup and is not halal."
        ),
    },
]


def policies_payload() -> dict[str, Any]:
    return {"sections": POLICY_SECTIONS, "version": POLICIES_VERSION}


def find_product(catalog: Mapping[str, Any], slug: str) -> dict[str, Any] | None:
    products = catalog.get("products") or []
    if not isinstance(products, Iterable):
        return None
    for p in products:
        if isinstance(p, Mapping) and p.get("slug") == slug:
            return dict(p)
    return None


def lookup_variation(catalog: Mapping[str, Any], slug: str) -> str | None:
    """Return the Square ``variationId`` for a slug, or ``None`` if missing.

    Used by ``POST /api/order`` to translate the customer-facing slug into
    the id ``square_create_order`` expects.
    """
    item = find_product(catalog, slug)
    if item is None:
        return None
    raw = item.get("variationId")
    return str(raw) if isinstance(raw, str) else None


def lookup_kitchen_product(catalog: Mapping[str, Any], slug: str) -> str | None:
    """Return the kitchen ``productId`` for a slug, or ``None`` if missing.

    The kitchen MCP tool family uses a different namespace from Square — slices
    are ``honey-cake-slice``, not ``sq_var_honey_cake_slice``. Slug → kitchen
    productId mapping lives in the catalog payload (``kitchenProductId`` key
    surfaced by ``shape_catalog``).
    """
    item = find_product(catalog, slug)
    if item is None:
        return None
    raw = item.get("kitchenProductId")
    return str(raw) if isinstance(raw, str) else None
