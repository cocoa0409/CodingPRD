"""Domain assertions and the integer arithmetic the PRD pins.

The rounding helpers exist so a test can spell the PRD's formula in the same
shape the PRD writes it — round half up by default, ceiling in the one place the
PRD names, floor in the two places it names — instead of hiding the arithmetic
behind a pre-computed literal with no derivation.
"""

from typing import Any, Dict, List, Mapping, Optional, Tuple

import requests

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_success,
)

from .api_client import canonical_instant
from .constants import (
    GARNISH_ALLOWANCE_BPS,
    GARNISH_FLOOR_MICROS,
    MICROS_PER_CENT,
    REGION_FREIGHT_UPLIFT_BPS,
    WASTE_FACTOR_BPS,
)

# ─── Integer arithmetic (PRD 2.5) ─────────────────────


def round_half_up(numerator: int, denominator: int) -> int:
    """Divide two integers rounding halves away from zero."""
    assert denominator > 0, "denominator must be positive"
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    return -((-2 * numerator + denominator) // (2 * denominator))


def floor_div(numerator: int, denominator: int) -> int:
    """Divide two integers truncating towards negative infinity."""
    assert denominator > 0, "denominator must be positive"
    return numerator // denominator


def ceil_div(numerator: int, denominator: int) -> int:
    """Divide two integers rounding up."""
    assert denominator > 0, "denominator must be positive"
    return -((-numerator) // denominator)


def net_yield_bps(trim_yield_bps: int, cook_shrink_bps: int) -> int:
    """The ingredient's usable fraction: floored, and never below one."""
    return max(1, floor_div(trim_yield_bps * (10000 - cook_shrink_bps), 10000))


def ap_quantity_for_ingredient(
    ep_quantity_base_units: int, net_yield_bps_value: int
) -> int:
    """As-purchased quantity from edible-portion quantity, rounded up."""
    return ceil_div(ep_quantity_base_units * 10000, net_yield_bps_value)


def plate_cost_micros(portion_cost_micros: int, region_code: str) -> int:
    """The four ordered plate-costing steps of PRD 3.5, each rounding half up."""
    uplift = REGION_FREIGHT_UPLIFT_BPS[region_code]
    landed = round_half_up(portion_cost_micros * (10000 + uplift), 10000)
    waste_adjusted = round_half_up(landed * WASTE_FACTOR_BPS, 10000)
    garnish = max(
        round_half_up(waste_adjusted * GARNISH_ALLOWANCE_BPS, 10000),
        GARNISH_FLOOR_MICROS,
    )
    return waste_adjusted + garnish


def micros_to_cents(micros: int) -> int:
    return round_half_up(micros, MICROS_PER_CENT)


# ─── Envelope and common-property assertions ──────────

_EXACT_MILLIS_LEN = len("2026-08-01T00:00:00.000Z")


def assert_instant_format(value: str) -> None:
    """An instant is ISO-8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str), f"instant must be a string, got {value!r}"
    assert is_iso8601_timestamp(value), f"not an ISO-8601 UTC instant: {value!r}"
    assert len(value) == _EXACT_MILLIS_LEN and value[19] == "." and value[-1] == "Z", (
        f"instant must carry exactly three fractional digits: {value!r}"
    )


def assert_instant_equals(actual: Any, expected: Any, label: str = "instant") -> None:
    """Compare two instants after normalising their fractional digits."""
    assert canonical_instant(actual) == canonical_instant(expected), (
        f"{label}: expected {expected!r}, got {actual!r}"
    )


def assert_common_props(entity: Mapping[str, Any], expected_version: Optional[int] = None) -> None:
    """Every resource carries an id, two audit stamps and a version."""
    assert is_valid_uuid(entity["id"]), f"id must be a bare UUID: {entity['id']!r}"
    assert not str(entity["id"]).startswith(("id_", "res_")), (
        "id must carry no prefix"
    )
    assert_instant_format(entity["created_at"])
    assert_instant_format(entity["updated_at"])
    assert isinstance(entity["version"], int), "version must be an integer"
    assert entity["version"] >= 1, "version starts at one"
    if expected_version is not None:
        assert entity["version"] == expected_version, (
            f"expected version {expected_version}, got {entity['version']}"
        )


def assert_success_envelope(
    response: requests.Response, expected_status: int = 200
) -> dict:
    """Validate the envelope and additionally the request-id prefix."""
    body = response.json()
    meta = body.get("meta", {})
    assert str(meta.get("api_request_id", "")).startswith("req_"), (
        f"meta.api_request_id must start with 'req_': {meta.get('api_request_id')!r}"
    )
    assert_instant_format(meta["api_request_timestamp"])
    return validate_success(response, expected_status)


def assert_error_envelope_shape(response: requests.Response) -> None:
    """An error envelope carries only the two meta fields and the two data fields."""
    body = response.json()
    assert body["response_type"] == "error"
    assert set(body["meta"].keys()) == {
        "api_request_id",
        "api_request_timestamp",
    }, f"error meta must carry exactly two fields, got {sorted(body['meta'])}"
    assert set(body["data"].keys()) == {"error_id", "message"}, (
        f"error data must carry exactly two fields, got {sorted(body['data'])}"
    )


def validate_unpaginated(
    response: requests.Response, expected_status: int = 200
) -> List[dict]:
    """Validate an array-typed response that carries no pagination meta."""
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body["response_type"] == "array", (
        f"expected response_type 'array', got {body.get('response_type')!r}"
    )
    assert isinstance(body["data"], list), "data must be a list"
    return body["data"]


def assert_page_meta(
    meta: Mapping[str, Any],
    total_count: int,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
    has_more: Optional[bool] = None,
) -> None:
    assert meta["total_count"] == total_count, (
        f"expected total_count {total_count}, got {meta['total_count']}"
    )
    if limit is not None:
        assert meta["limit"] == limit
    if offset is not None:
        assert meta["offset"] == offset
    if has_more is not None:
        assert meta["has_more"] is has_more, (
            f"expected has_more {has_more}, got {meta['has_more']}"
        )


def assert_fields(entity: Mapping[str, Any], **expected: Any) -> None:
    """Assert an exact value for each named field, reporting all mismatches."""
    problems = []
    for field, want in expected.items():
        assert field in entity, f"field {field!r} missing from {sorted(entity)}"
        got = entity[field]
        if isinstance(want, str) and isinstance(got, str) and "T" in want and want.endswith("Z"):
            got_cmp, want_cmp = canonical_instant(got), canonical_instant(want)
        else:
            got_cmp, want_cmp = got, want
        if got_cmp != want_cmp:
            problems.append(f"{field}: expected {want!r}, got {got!r}")
    assert not problems, "; ".join(problems)


def assert_integer_fields(entity: Mapping[str, Any], *fields: str) -> None:
    """Money, quantity and basis-point fields are JSON numbers, never strings."""
    for field in fields:
        value = entity[field]
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{field} must be a JSON integer, got {value!r} ({type(value).__name__})"
        )


def assert_ordered_by(
    rows: List[Mapping[str, Any]], key: str, descending: bool = False
) -> None:
    values = [row[key] for row in rows]
    expected = sorted(values, reverse=descending)
    assert values == expected, (
        f"rows are not ordered by {key} "
        f"{'DESC' if descending else 'ASC'}: {values}"
    )


def ids_of(rows: List[Mapping[str, Any]]) -> List[str]:
    return [row["id"] for row in rows]


# ─── Per-entity assertions ────────────────────────────


def assert_ingredient(
    ingredient: Mapping[str, Any], **expected: Any
) -> None:
    assert_common_props(ingredient)
    assert_integer_fields(
        ingredient,
        "pack_base_units",
        "trim_yield_bps",
        "cook_shrink_bps",
        "net_yield_bps",
        "allergen_mask",
        "kcal_per_base_unit_micros",
        "sodium_mcg_per_base_unit",
    )
    assert ingredient["net_yield_bps"] == net_yield_bps(
        ingredient["trim_yield_bps"], ingredient["cook_shrink_bps"]
    ), "net_yield_bps must be the floored product of trim and shrink"
    assert_fields(ingredient, **expected)


def assert_price_feed(feed: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(feed)
    assert_integer_fields(
        feed,
        "line_count",
        "superseded_price_count",
        "affected_recipe_count",
        "affected_menu_item_count",
    )
    assert_fields(feed, **expected)


def assert_ingredient_price(price: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(price)
    assert_integer_fields(price, "pack_cost_micros", "pack_base_units_snapshot")
    assert_instant_format(price["effective_from"])
    if price.get("effective_to") is not None:
        assert_instant_format(price["effective_to"])
    assert_fields(price, **expected)


def assert_recipe(recipe: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(recipe)
    assert_integer_fields(
        recipe,
        "batch_yield_base_units",
        "portions_per_batch",
        "batch_cost_micros",
        "portion_cost_micros",
        "allergen_mask",
        "kcal_per_portion_micros",
        "sodium_mcg_per_portion",
        "component_count",
        "depth",
        "open_spec_change_count",
    )
    assert_fields(recipe, **expected)


def assert_recipe_component(component: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(component)
    assert_integer_fields(
        component,
        "ep_quantity_base_units",
        "ap_quantity_base_units",
        "sequence_no",
    )
    assert_fields(component, **expected)


def assert_prep_guide(guide: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(guide)
    assert_integer_fields(
        guide,
        "revision_no",
        "synced_spec_version",
        "component_count_snapshot",
        "batch_yield_base_units_snapshot",
        "portions_per_batch_snapshot",
    )
    assert_fields(guide, **expected)


def assert_menu_item(item: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(item)
    assert_integer_fields(
        item,
        "current_price_cents",
        "target_food_cost_bps",
        "declared_allergen_mask",
        "plate_cost_micros",
        "plate_cost_cents",
        "food_cost_bps",
        "contribution_margin_cents",
        "allergen_mask",
        "sodium_mcg_per_portion",
        "open_lto_count",
    )
    assert isinstance(item["is_kids_menu"], bool), "is_kids_menu must be a boolean"
    assert isinstance(item["is_lto"], bool), "is_lto must be a boolean"
    assert_fields(item, **expected)


def assert_proposal(proposal: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(proposal)
    assert_integer_fields(
        proposal, "proposed_price_cents", "elasticity_bps", "revision_round"
    )
    assert_fields(proposal, **expected)


def assert_projections_unset(proposal: Mapping[str, Any]) -> None:
    """Before a successful submission every projection field is null."""
    for field in (
        "price_delta_bps",
        "projected_unit_delta_bps",
        "baseline_units",
        "projected_units",
        "projected_food_cost_bps",
        "market_cap_price_cents",
        "effective_cap_price_cents",
        "projected_contribution_delta_cents",
    ):
        assert proposal[field] is None, (
            f"{field} must still be null, got {proposal[field]!r}"
        )


def assert_spec_change_order(order: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(order)
    assert_fields(order, **expected)


def assert_period_review(review: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(review)
    assert_integer_fields(review, "total_units_sold", "total_gross_sales_cents")
    assert_fields(review, **expected)


def assert_mix_line(line: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(line)
    assert_integer_fields(
        line, "units_sold", "gross_sales_cents", "plate_cost_cents_snapshot"
    )
    assert_fields(line, **expected)


def assert_count_line(line: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(line)
    assert_integer_fields(
        line,
        "opening_base_units",
        "received_base_units",
        "counted_base_units",
        "used_base_units",
        "expected_base_units",
        "variance_base_units",
        "valued_usage_micros",
    )
    assert line["variance_base_units"] == (
        line["used_base_units"] - line["expected_base_units"]
    ), "variance is used minus expected"
    assert_fields(line, **expected)


def assert_lto_campaign(campaign: Mapping[str, Any], **expected: Any) -> None:
    assert_common_props(campaign)
    assert_integer_fields(
        campaign,
        "promo_price_cents",
        "forecast_units",
        "promo_plate_cost_cents",
        "promo_food_cost_bps",
        "forecast_contribution_cents",
        "promo_support_cost_cents",
        "promo_contribution_cents",
        "forecast_attainment_bps",
    )
    assert_fields(campaign, **expected)


# ─── Invariant checkers ───────────────────────────────


def assert_unchanged(
    before: Mapping[str, Any], after: Mapping[str, Any], *fields: str
) -> None:
    """Assert that a cascade left the named fields exactly as they were."""
    problems = []
    for field in fields:
        if before[field] != after[field]:
            problems.append(f"{field}: was {before[field]!r}, now {after[field]!r}")
    assert not problems, "expected these fields untouched: " + "; ".join(problems)


def assert_version_advanced_by(
    before: Mapping[str, Any], after: Mapping[str, Any], increment: int
) -> None:
    assert after["version"] == before["version"] + increment, (
        f"expected version {before['version']} + {increment}, got {after['version']}"
    )


def assert_cost_figures_frozen(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    """Going stale never clears the last figures a roll-up wrote."""
    assert_unchanged(
        before,
        after,
        "batch_cost_micros",
        "portion_cost_micros",
        "allergen_mask",
        "kcal_per_portion_micros",
        "sodium_mcg_per_portion",
    )


def assert_plate_figures_frozen(
    before: Mapping[str, Any], after: Mapping[str, Any]
) -> None:
    assert_unchanged(
        before, after, "plate_cost_micros", "plate_cost_cents", "food_cost_bps"
    )


def single_row(rows: List[dict], meta: Optional[Mapping[str, Any]] = None) -> dict:
    """Assert a listing returned exactly one row and hand it back."""
    assert len(rows) == 1, f"expected exactly one row, got {len(rows)}"
    if meta is not None:
        assert meta["total_count"] == 1, (
            f"expected total_count 1, got {meta['total_count']}"
        )
    return rows[0]


def sole_prep_guide(response: requests.Response) -> Tuple[Dict[str, Any], dict]:
    """A recipe has zero or one prep guide; return the one row and the meta."""
    body = response.json()
    rows, meta = body["data"], body["meta"]
    return single_row(rows, meta), meta
