"""Inclusive and exclusive boundaries: the approval tier, the daypart end, the low-stock line."""

import os
import sys
from typing import Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import validate_success  # noqa: E402

from test_helpers import factories as f  # noqa: E402
from test_helpers.assertions import assert_fields, assert_money  # noqa: E402
from test_helpers.constants import (  # noqa: E402
    AVAIL_AVAILABLE,
    AVAIL_LIMITED,
    CATEGORY_ENTREE,
    CLOCK_T0,
    LISTING_LISTED,
    LUNCH_CODE,
    LUNCH_LAYOUT,
    PCR_DRAFT,
    PHASE_ACTIVE,
    PHASE_FALLBACK,
    PHASE_TRANSITIONING,
    ROUNDING_NONE,
    SKU_BURGER,
    STATIC_FALLBACK,
    STORE_CODE_S001,
    SUPPLY_IN_STOCK,
    SUPPLY_LOW,
    ZONE_B_CODE,
    ZONE_B_MAX_UPLIFT_BP,
    ZONE_B_MULTIPLIER_BP,
    ZONE_B_TAX_BP,
    ZONE_A_CODE,
)
from test_helpers.fixtures import World, publish_bundle_with_slot  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    ADMIN,
    ANALYST,
    CONTENT_MANAGER,
    make_store_operator_headers,
)


def _unrounded_zone(api) -> Dict[str, Any]:
    """ZONE_B applies no psychological rounding, so the baseline is a clean 600."""
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_B_CODE, price_multiplier_bp=ZONE_B_MULTIPLIER_BP,
                     psychological_rounding=ROUNDING_NONE, tax_rate_bp=ZONE_B_TAX_BP,
                     max_uplift_bp=ZONE_B_MAX_UPLIFT_BP)
    cluster = world.cluster("CL_ZONE")
    world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    return {"world": world, "zone": zone, "burger": burger}


def test_an_uplift_of_exactly_five_hundred_basis_points_demands_two_approvers(api):
    """PRD: "Third, `required_approvals` is 2 when `uplift_bp` reached 500 basis points — five percent — and 1 otherwise."

    Design: Difficulty/boundary_precision_check/dual_approval_uplift_at_exactly_five_hundred_basis_points
    """
    scene = _unrounded_zone(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]
    live_version = world.get_item(burger["id"])["version"]

    response = api.create_price_change_request(
        f.price_change_request_payload(burger["id"], zone["id"], 630, CLOCK_T0, live_version,
                                       justification="At the dual approval boundary"),
        ANALYST,
    )
    request = validate_success(response, 201)

    assert_money(request["baseline_price_cents"], 600, "baseline_price_cents")
    assert_fields(request, uplift_bp=500, required_approvals=2, state=PCR_DRAFT)


def test_one_cent_below_the_boundary_falls_a_tier(api):
    """PRD: "Second, `uplift_bp` is the basis-point uplift of the raw proposal over that baseline: the baseline is subtracted from `proposed_price_cents`, the difference is multiplied by 10000, the product is divided by `baseline_price_cents`, and the quotient is rounded half up to a whole basis point."

    Design: Difficulty/boundary_precision_check/dual_approval_uplift_at_exactly_five_hundred_basis_points
    """
    scene = _unrounded_zone(api)
    world, burger, zone = scene["world"], scene["burger"], scene["zone"]
    live_version = world.get_item(burger["id"])["version"]

    response = api.create_price_change_request(
        f.price_change_request_payload(burger["id"], zone["id"], 629, CLOCK_T0, live_version,
                                       justification="One cent below the boundary"),
        ANALYST,
    )
    request = validate_success(response, 201)

    assert_money(request["baseline_price_cents"], 600, "baseline_price_cents")
    assert_fields(request, uplift_bp=483, required_approvals=1, state=PCR_DRAFT)


def _published_lunch_only_bundle(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    bundle = publish_bundle_with_slot(world, cluster["id"], category_codes=[CATEGORY_ENTREE])
    return {"world": world, "store": store, "burger": burger, "bundle": bundle}


def _projection_at(api, store_id: str, minute: int) -> Dict[str, Any]:
    return validate_success(
        api.get_menu_projection(store_id, CONTENT_MANAGER,
                                params=f.projection_params(at_minute_of_day=minute)),
        200,
    )


def test_the_transition_buffer_edge_is_inclusive(api):
    """PRD: "The winner's `daypart_code` and `layout_code` are returned, and `phase` is `TRANSITIONING` when the resolved minute is at or after the winner's `end_minute_of_day` minus its `buffer_minutes`, and `ACTIVE` otherwise."

    Design: Difficulty/boundary_precision_check/daypart_containment_at_exclusive_end_minute_falls_back
    """
    scene = _published_lunch_only_bundle(api)
    store_id = scene["store"]["id"]

    at_944 = _projection_at(api, store_id, 944)
    assert_fields(at_944, daypart_code=LUNCH_CODE, layout_code=LUNCH_LAYOUT, phase=PHASE_ACTIVE)

    at_945 = _projection_at(api, store_id, 945)
    assert at_945["phase"] == PHASE_TRANSITIONING, (
        f"960 - 15 = 945 is inside the buffer, got phase {at_945['phase']!r}"
    )


def test_the_slot_end_minute_itself_falls_back_to_the_static_layout(api):
    """PRD: "The interval is half-open, so a slot running from 600 to 900 covers minute 899 but not minute 900, and two slots of the same bundle must not overlap; an overlapping interval, or one whose start is not strictly below its end, is refused with `ERR_DAYPART_SLOT_OVERLAP`."

    Design: Difficulty/boundary_precision_check/daypart_containment_at_exclusive_end_minute_falls_back
    """
    scene = _published_lunch_only_bundle(api)
    store_id, bundle = scene["store"]["id"], scene["bundle"]

    at_959 = _projection_at(api, store_id, 959)
    assert_fields(at_959, daypart_code=LUNCH_CODE, layout_code=LUNCH_LAYOUT,
                  phase=PHASE_TRANSITIONING, local_minute_of_day=959)
    assert at_959["resolved_bundle_id"] == bundle["id"]

    at_960 = _projection_at(api, store_id, 960)
    assert at_960["daypart_code"] is None, (
        f"minute 960 is outside [660, 960), got {at_960['daypart_code']!r}"
    )
    assert_fields(at_960, layout_code=STATIC_FALLBACK, phase=PHASE_FALLBACK,
                  local_minute_of_day=960)


def _stocked_row(api) -> Dict[str, Any]:
    world = World(api)
    world.set_clock(CLOCK_T0)
    zone = world.zone(ZONE_A_CODE)
    cluster = world.cluster("CL_WEST")
    store = world.store(cluster["id"], zone["id"], STORE_CODE_S001)
    burger = world.item(SKU_BURGER, category=CATEGORY_ENTREE, base_price_cents=500)
    row = world.availability(store["id"], burger["id"], on_hand_units=40, par_units=20)
    return {"world": world, "store": store, "burger": burger, "row": row}


def test_one_unit_above_the_low_stock_threshold_is_still_in_stock(api):
    """PRD: "The low-stock threshold is 20 percent of `par_units` — that is, `par_units` multiplied by 2000 basis points and divided by 10000 — rounded half up to a whole unit."

    Design: Difficulty/boundary_precision_check/low_stock_threshold_inclusive_at_par_ratio_units
    """
    scene = _stocked_row(api)
    assert_fields(scene["row"], supply_state=SUPPLY_IN_STOCK, availability_state=AVAIL_AVAILABLE,
                  available_units=40)

    response = api.item_availability_action(
        scene["row"]["id"], f.sync_on_hand_payload(5),
        make_store_operator_headers(scene["store"]["id"]),
    )
    row = validate_success(response, 200)

    assert_fields(row, available_units=5, supply_state=SUPPLY_IN_STOCK,
                  availability_state=AVAIL_AVAILABLE)


def test_the_low_stock_threshold_itself_is_already_low(api):
    """PRD: "`supply_state` is `DEPLETED` when `available_units` is 0 or below; `LOW` when it is at or below the threshold, the boundary being inclusive; and `IN_STOCK` otherwise."

    Design: Difficulty/boundary_precision_check/low_stock_threshold_inclusive_at_par_ratio_units
    """
    scene = _stocked_row(api)

    response = api.item_availability_action(
        scene["row"]["id"], f.sync_on_hand_payload(4),
        make_store_operator_headers(scene["store"]["id"]),
    )
    row = validate_success(response, 200)

    assert_fields(row, available_units=4, supply_state=SUPPLY_LOW,
                  availability_state=AVAIL_LIMITED, listing_state=LISTING_LISTED)

    item = validate_success(api.get_menu_item(scene["burger"]["id"], ADMIN), 200)
    assert item["chainwide_availability_state"] == AVAIL_LIMITED, (
        "the rollup reads LIMITED when no row is available and at least one is limited"
    )
