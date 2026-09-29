"""Entity serialisers. Every entity exposes the four common fields (PRD 2.4)
plus exactly the properties the PRD declares for it -- nothing else."""
import datetime

from core import fmt_instant

COMMON = ("id", "created_at", "updated_at", "version")

FIELDS = {
    "unit": ("code", "name", "region_code"),
    "ingredient": (
        "sku", "name", "base_uom", "pack_base_units", "trim_yield_bps",
        "cook_shrink_bps", "net_yield_bps", "allergen_mask",
        "kcal_per_base_unit_micros", "sodium_mcg_per_base_unit", "status",
        "retired_at",
    ),
    "price_feed": (
        "distributor_code", "region_code", "feed_date", "status", "line_count",
        "published_at", "superseded_price_count", "affected_recipe_count",
        "affected_menu_item_count",
    ),
    "ingredient_price": (
        "ingredient_id", "price_feed_id", "region_code", "distributor_code",
        "pack_cost_micros", "pack_base_units_snapshot", "effective_from",
        "effective_to", "status",
    ),
    "recipe": (
        "code", "name", "recipe_type", "base_uom", "batch_yield_base_units",
        "portions_per_batch", "status", "cost_state", "cost_basis",
        "batch_cost_micros", "portion_cost_micros", "allergen_mask",
        "kcal_per_portion_micros", "sodium_mcg_per_portion", "depth",
        "component_count", "open_spec_change_count", "last_rollup_at",
    ),
    "recipe_component": (
        "recipe_id", "component_type", "ingredient_id", "child_recipe_id",
        "ep_quantity_base_units", "ap_quantity_base_units",
        "unit_cost_micros_used", "pack_base_units_snapshot",
        "extended_cost_micros", "sequence_no", "status", "removed_at",
    ),
    "prep_guide": (
        "recipe_id", "revision_no", "sync_state",
        "batch_yield_base_units_snapshot", "portions_per_batch_snapshot",
        "component_count_snapshot", "synced_spec_version",
    ),
    "menu_item": (
        "code", "name", "recipe_id", "region_code", "current_price_cents",
        "target_food_cost_bps", "declared_allergen_mask", "is_kids_menu",
        "is_lto", "open_lto_count", "plate_cost_micros", "plate_cost_cents",
        "food_cost_bps", "contribution_margin_cents", "plate_cost_state",
        "cost_basis", "allergen_mask", "sodium_mcg_per_portion",
        "margin_class", "status", "last_price_change_at",
    ),
    "proposal": (
        "menu_item_id", "proposed_price_cents", "effective_from",
        "elasticity_bps", "status", "revision_round", "submitted_by_user_id",
        "approved_by_user_id", "last_revision_reason", "baseline_units",
        "price_delta_bps", "projected_unit_delta_bps", "projected_units",
        "projected_food_cost_bps", "market_cap_price_cents",
        "effective_cap_price_cents", "projected_contribution_delta_cents",
        "applied_at",
    ),
    "spec_change_order": (
        "recipe_id", "change_type", "target_component_id", "ingredient_id",
        "new_ep_quantity_base_units", "approval_status", "propagation_status",
        "submitted_by_user_id", "approved_by_user_id", "rejection_reason",
        "created_component_id", "pre_change_ep_quantity_base_units",
        "pre_change_batch_cost_micros", "pre_change_allergen_mask",
        "pre_change_recipe_version", "approved_at",
    ),
    "period_review": (
        "unit_id", "period_start", "period_end", "basis", "status",
        "total_units_sold", "total_gross_sales_cents",
        "popularity_threshold_bps", "margin_threshold_cents",
        "theoretical_food_cost_cents", "actual_food_cost_cents",
        "variance_bps", "variance_flag", "closed_at",
    ),
    "mix_line": (
        "period_review_id", "menu_item_id", "units_sold", "gross_sales_cents",
        "plate_cost_cents_snapshot", "mix_pct_bps", "cm_per_unit_cents",
        "margin_class",
    ),
    "count_line": (
        "period_review_id", "ingredient_id", "opening_base_units",
        "received_base_units", "counted_base_units", "used_base_units",
        "expected_base_units", "variance_base_units", "valued_usage_micros",
        "sync_state", "synced_spec_version",
    ),
    "lto_campaign": (
        "menu_item_id", "region_code", "window_start", "window_end",
        "promo_price_cents", "forecast_units", "status",
        "promo_plate_cost_cents", "promo_food_cost_bps",
        "forecast_contribution_cents", "actual_units",
        "actual_gross_sales_cents", "promo_support_cost_cents",
        "promo_contribution_cents", "forecast_attainment_bps", "verdict",
        "reviewed_at",
    ),
}


def _value(value):
    if isinstance(value, datetime.datetime):
        return fmt_instant(value)
    return value


def _ser(kind, row):
    out = {}
    for name in COMMON:
        out[name] = _value(row.get(name))
    for name in FIELDS[kind]:
        out[name] = _value(row.get(name))
    return out


def unit(row):
    return _ser("unit", row)


def ingredient(row):
    return _ser("ingredient", row)


def price_feed(row):
    return _ser("price_feed", row)


def ingredient_price(row):
    return _ser("ingredient_price", row)


def recipe(row):
    return _ser("recipe", row)


def recipe_component(row):
    return _ser("recipe_component", row)


def prep_guide(row):
    return _ser("prep_guide", row)


def menu_item(row):
    return _ser("menu_item", row)


def proposal(row):
    return _ser("proposal", row)


def spec_change_order(row):
    return _ser("spec_change_order", row)


def period_review(row):
    return _ser("period_review", row)


def mix_line(row):
    return _ser("mix_line", row)


def count_line(row):
    return _ser("count_line", row)


def lto_campaign(row):
    return _ser("lto_campaign", row)
