from __future__ import annotations

from datetime import datetime

from src.webhooks.storefront import (
    POLICY_SECTIONS,
    find_product,
    format_cake_name,
    policies_payload,
    shape_catalog,
    slugify,
)


def test_format_cake_name_uses_known_map() -> None:
    assert (
        format_cake_name("Honey cake slice", kitchen_product_id="honey-cake-slice")
        == 'cake "Honey" — slice'
    )


def test_format_cake_name_heuristic_for_unknown() -> None:
    assert format_cake_name("Tiramisu cake whole") == 'cake "Tiramisu" — whole'


def test_format_cake_name_falls_through_for_non_cake() -> None:
    assert format_cake_name("office dessert box") == "office dessert box"


def test_slugify_lowers_and_kebabs() -> None:
    assert slugify("cake \"Honey\" — slice!") == "cake-honey-slice"


def test_shape_catalog_maps_mcp_payload_to_contract() -> None:
    raw = {
        "mode": "simulated",
        "catalog": [
            {
                "id": "sq_item_honey_cake_slice",
                "variationId": "sq_var_honey_cake_slice",
                "name": "Honey cake slice",
                "category": "slices",
                "priceCents": 850,
                "description": "Individual honey cake slice for walk-ins.",
                "kitchenProductId": "honey-cake-slice",
            }
        ],
    }
    kitchen = {
        "dailyCapacityMinutes": 420,
        "remainingCapacityMinutes": 240,
        "overCapacity": False,
    }
    out = shape_catalog(raw, kitchen=kitchen, fetched_at=datetime(2026, 5, 9))
    assert out["source"] == "happycake_mcp"
    assert out["kitchen"]["remainingCapacityMinutes"] == 240
    assert len(out["products"]) == 1
    p = out["products"][0]
    assert p["slug"] == "honey-cake-slice"
    assert p["name"] == 'cake "Honey" — slice'
    assert p["priceUsd"] == 8.50
    assert p["priceFormatted"] == "$8.50"
    assert p["image"].endswith(".webp")


def test_shape_catalog_handles_empty_catalog() -> None:
    out = shape_catalog({"catalog": []})
    assert out["products"] == []


def test_shape_catalog_handles_missing_payload() -> None:
    out = shape_catalog(None)
    assert out["products"] == []
    assert out["source"] == "happycake_mcp"


def test_policies_payload_has_all_required_sections() -> None:
    payload = policies_payload()
    ids = {s["id"] for s in payload["sections"]}
    assert {"pickup", "delivery", "lead_times", "refunds", "allergens", "halal"}.issubset(ids)
    assert payload["version"] == 1
    assert payload["sections"] is POLICY_SECTIONS  # same object, no copy


def test_find_product_by_slug() -> None:
    catalog = shape_catalog(
        {
            "catalog": [
                {
                    "id": "x",
                    "variationId": "v",
                    "name": "Honey cake slice",
                    "priceCents": 850,
                    "kitchenProductId": "honey-cake-slice",
                }
            ]
        }
    )
    assert find_product(catalog, "honey-cake-slice")["priceUsd"] == 8.50
    assert find_product(catalog, "missing") is None
