"""Request-payload builders.

Each factory returns a plain dict with the PRD's field names.  Money, quantity,
basis-point and bitmask fields are always JSON numbers — never strings — and
every instant is a full ISO-8601 UTC timestamp with three fractional digits,
never a bare date.

Derived factories merge their caller's overrides into a dict before delegating,
so no factory ever passes the same keyword twice.
"""

from typing import Any, Dict

from .constants import CLOCK_EPOCH
from .types import (
    BaseUom,
    ChangeType,
    ComponentType,
    CostBasis,
    DistributorCode,
    LtoDecision,
    PropagationTarget,
    RecipeType,
    RegionCode,
    ReviewBasis,
)

Payload = Dict[str, Any]


def _merged(base: Payload, overrides: Payload) -> Payload:
    merged = dict(base)
    merged.update(overrides)
    return merged


# ─── clock ────────────────────────────────────────────


def clock_payload(to_iso8601: str) -> Payload:
    return {"to_iso8601": to_iso8601}


# ─── units ────────────────────────────────────────────


def unit_payload(**overrides: Any) -> Payload:
    return _merged(
        {
            "code": "STORE-001",
            "name": "Downtown",
            "region_code": RegionCode.MW,
        },
        overrides,
    )


# ─── ingredients ──────────────────────────────────────


def ingredient_payload(**overrides: Any) -> Payload:
    return _merged(
        {
            "sku": "GENERIC-ITEM",
            "name": "Generic Item",
            "base_uom": BaseUom.GRAM,
            "pack_base_units": 1000,
            "trim_yield_bps": 10000,
            "cook_shrink_bps": 0,
            "allergen_mask": 0,
            "kcal_per_base_unit_micros": 0,
            "sodium_mcg_per_base_unit": 0,
        },
        overrides,
    )


def cheddar_block_payload(**overrides: Any) -> Payload:
    """Cheddar in 2268-gram blocks: no trim loss, no shrink, milk allergen."""
    return ingredient_payload(
        **_merged(
            {
                "sku": "CHEDDAR-BLOCK",
                "name": "Cheddar Block",
                "base_uom": BaseUom.GRAM,
                "pack_base_units": 2268,
                "trim_yield_bps": 10000,
                "cook_shrink_bps": 0,
                "allergen_mask": 1,
                "kcal_per_base_unit_micros": 4000000,
                "sodium_mcg_per_base_unit": 6200,
            },
            overrides,
        )
    )


def peanut_oil_payload(**overrides: Any) -> Payload:
    """Peanut oil in 946-millilitre jugs: peanut allergen, no sodium."""
    return ingredient_payload(
        **_merged(
            {
                "sku": "PEANUT-OIL",
                "name": "Peanut Oil",
                "base_uom": BaseUom.MILLILITER,
                "pack_base_units": 946,
                "trim_yield_bps": 10000,
                "cook_shrink_bps": 0,
                "allergen_mask": 8,
                "kcal_per_base_unit_micros": 8000000,
                "sodium_mcg_per_base_unit": 0,
            },
            overrides,
        )
    )


# ─── price feeds and price lines ──────────────────────


def price_feed_payload(**overrides: Any) -> Payload:
    return _merged(
        {
            "distributor_code": DistributorCode.BROADLINE,
            "region_code": RegionCode.MW,
            "feed_date": "2026-07-01T00:00:00.000Z",
        },
        overrides,
    )


def price_line_payload(ingredient_id: str, **overrides: Any) -> Payload:
    """A price line: ``effective_to`` is only sent when the caller asks for it."""
    return _merged(
        {
            "ingredient_id": ingredient_id,
            "pack_cost_micros": 22000000,
            "effective_from": "2026-07-01T00:00:00.000Z",
        },
        overrides,
    )


# ─── recipes and components ───────────────────────────


def recipe_payload(**overrides: Any) -> Payload:
    return _merged(
        {
            "code": "PLATE-GRILL",
            "name": "Grilled Cheese Plate",
            "recipe_type": RecipeType.PLATED,
            "base_uom": BaseUom.EACH,
            "batch_yield_base_units": 4,
            "portions_per_batch": 4,
        },
        overrides,
    )


def plated_recipe_payload(**overrides: Any) -> Payload:
    return recipe_payload(**_merged({"recipe_type": RecipeType.PLATED}, overrides))


def sub_recipe_payload(**overrides: Any) -> Payload:
    return recipe_payload(
        **_merged(
            {
                "code": "SUB-CHEESE",
                "name": "Cheese Sauce",
                "recipe_type": RecipeType.SUB_RECIPE,
                "base_uom": BaseUom.GRAM,
                "batch_yield_base_units": 2000,
                "portions_per_batch": 20,
            },
            overrides,
        )
    )


def ingredient_component_payload(
    ingredient_id: str, expected_recipe_version: int, **overrides: Any
) -> Payload:
    return _merged(
        {
            "component_type": ComponentType.INGREDIENT,
            "ingredient_id": ingredient_id,
            "ep_quantity_base_units": 400,
            "sequence_no": 1,
            "expected_recipe_version": expected_recipe_version,
        },
        overrides,
    )


def sub_recipe_component_payload(
    child_recipe_id: str, expected_recipe_version: int, **overrides: Any
) -> Payload:
    return _merged(
        {
            "component_type": ComponentType.SUB_RECIPE,
            "child_recipe_id": child_recipe_id,
            "ep_quantity_base_units": 500,
            "sequence_no": 1,
            "expected_recipe_version": expected_recipe_version,
        },
        overrides,
    )


def component_delete_params(expected_recipe_version: int, **overrides: Any) -> Payload:
    return _merged({"expected_recipe_version": expected_recipe_version}, overrides)


def rollup_payload(**overrides: Any) -> Payload:
    return _merged({"basis": CostBasis.LATEST_PUBLISHED}, overrides)


# ─── menu items ───────────────────────────────────────


def menu_item_payload(recipe_id: str, **overrides: Any) -> Payload:
    return _merged(
        {
            "code": "MI-GRILL-MW",
            "name": "Grilled Cheese",
            "recipe_id": recipe_id,
            "region_code": RegionCode.MW,
            "current_price_cents": 400,
            "target_food_cost_bps": 3000,
            "declared_allergen_mask": 1,
        },
        overrides,
    )


# ─── price change proposals ───────────────────────────


def proposal_payload(menu_item_id: str, **overrides: Any) -> Payload:
    return _merged(
        {
            "menu_item_id": menu_item_id,
            "proposed_price_cents": 420,
            "effective_from": "2026-09-01T00:00:00.000Z",
            "elasticity_bps": 12000,
        },
        overrides,
    )


def revision_payload(reason: str = "trim the increase", **overrides: Any) -> Payload:
    return _merged({"last_revision_reason": reason}, overrides)


# ─── spec change orders ───────────────────────────────


def component_qty_change_payload(
    recipe_id: str,
    target_component_id: str,
    expected_recipe_version: int,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "recipe_id": recipe_id,
            "change_type": ChangeType.COMPONENT_QTY,
            "target_component_id": target_component_id,
            "new_ep_quantity_base_units": 600,
            "expected_recipe_version": expected_recipe_version,
        },
        overrides,
    )


def component_add_change_payload(
    recipe_id: str,
    new_ingredient_id: str,
    expected_recipe_version: int,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "recipe_id": recipe_id,
            "change_type": ChangeType.COMPONENT_ADD,
            "new_component_type": ComponentType.INGREDIENT,
            "new_ingredient_id": new_ingredient_id,
            "new_ep_quantity_base_units": 50,
            "expected_recipe_version": expected_recipe_version,
        },
        overrides,
    )


def component_remove_change_payload(
    recipe_id: str,
    target_component_id: str,
    expected_recipe_version: int,
    **overrides: Any,
) -> Payload:
    return _merged(
        {
            "recipe_id": recipe_id,
            "change_type": ChangeType.COMPONENT_REMOVE,
            "target_component_id": target_component_id,
            "expected_recipe_version": expected_recipe_version,
        },
        overrides,
    )


def propagate_payload(target: str = PropagationTarget.PREP_GUIDE) -> Payload:
    return {"target": target}


# ─── period reviews, mix lines and count lines ────────


def period_review_payload(unit_id: str, **overrides: Any) -> Payload:
    return _merged(
        {
            "unit_id": unit_id,
            "period_start": "2026-07-01T00:00:00.000Z",
            "period_end": "2026-08-01T00:00:00.000Z",
            "basis": ReviewBasis.SALES_MIX_BASED,
        },
        overrides,
    )


def mix_line_payload(menu_item_id: str, **overrides: Any) -> Payload:
    return _merged(
        {
            "menu_item_id": menu_item_id,
            "units_sold": 100,
            "gross_sales_cents": 40000,
        },
        overrides,
    )


def count_line_payload(ingredient_id: str, **overrides: Any) -> Payload:
    return _merged(
        {
            "ingredient_id": ingredient_id,
            "opening_base_units": 10000,
            "received_base_units": 0,
            "counted_base_units": 1800,
        },
        overrides,
    )


# ─── limited-time offer campaigns ─────────────────────


def lto_campaign_payload(
    menu_item_id: str, expected_menu_item_version: int, **overrides: Any
) -> Payload:
    return _merged(
        {
            "menu_item_id": menu_item_id,
            "window_start": "2026-08-05T00:00:00.000Z",
            "window_end": "2026-08-15T00:00:00.000Z",
            "promo_price_cents": 380,
            "forecast_units": 500,
            "expected_menu_item_version": expected_menu_item_version,
        },
        overrides,
    )


def close_review_payload(
    actual_units: int, actual_gross_sales_cents: int
) -> Payload:
    return {
        "actual_units": actual_units,
        "actual_gross_sales_cents": actual_gross_sales_cents,
    }


def decide_payload(decision: str = LtoDecision.RENEW) -> Payload:
    return {"decision": decision}


# The instant every scenario starts from, re-exported for payload authors.
EPOCH = CLOCK_EPOCH
