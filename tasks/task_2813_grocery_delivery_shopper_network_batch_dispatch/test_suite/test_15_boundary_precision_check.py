"""Difficulty rule boundary_precision_check.

An inclusive weight threshold hit exactly, and an empty candidate pool produced
by a capacity comparison that misses by one unit.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_ELIGIBLE_SHOPPER
from test_helpers.assertions import (
    assert_fields,
    assert_null_instant,
    assert_one_decimal,
    payout_for_batch,
    read_batch,
    read_shopper,
)
from test_helpers.constants import BATCH_BUILDING, CLOCK_0800
from test_helpers.test_users import ADMIN_HEADERS, make_shopper_headers


def _fifty_pound_batch(api):
    """Batch B9: five EACH units of a 10.0 lb item over 5.0 miles, checked out."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(
        api, legal_name="Harbor Foods Co", store_code="HF-04", catalog_markup_pct=0.15
    )
    r4 = retailer["id"]
    i6 = fx.make_catalog_item_each(
        api, r4, sku="SKU-HEAVY", name="Rice Sack",
        in_store_price_cents=200, is_ebt_eligible=True, unit_weight_lb=10.0,
    )
    customer = fx.make_customer(api, display_name="Owen Diaz", card_last4="3131")
    c4 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name="Mira Kaur", service_area_code="SF-04", vehicle_capacity_units=10
    )
    s4 = shopper["id"]
    order = fx.make_draft_order(
        api, c4, r4, delivery_distance_mi=5.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    line = fx.add_line_each(api, order["id"], c4, i6["id"], 5)
    fx.submit_order(api, order["id"], c4)
    batch = fx.make_batch(
        api, service_area_code="SF-04",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], order["id"])
    fx.dispatch(api, batch["id"])
    fx.claim(api, batch["id"], s4)
    fx.start_shopping(api, batch["id"], s4)
    fx.pick_each(api, line["id"], s4, 5)
    fx.checkout(api, batch["id"], s4)
    return {"batch": batch, "order": order, "shopper": shopper}


def test_heavy_pay_pays_the_first_tier_at_exactly_fifty_pounds(api):
    """PRD 3.8: "`heavy_pay_cents` is a weight-tier bonus, evaluated top down with
    inclusive thresholds: 900 cents once the batch's `total_weight_lb` reaches
    120.0 pounds, otherwise 600 cents once it reaches 80.0 pounds, otherwise 300
    cents once it reaches 50.0 pounds, otherwise 0" and mileage "Subtract 8.0
    miles from the batch's `total_distance_mi`; if the result is negative use 0.0
    instead".

    Five 10.0 lb units weigh exactly 50.0 lb, so the inclusive first tier pays
    300 - neither 0 from an exclusive comparison nor 600 from the tier above -
    while 5.0 miles is inside the free allowance and base pay is 700 + 25 * 5.

    Design: Difficulty/boundary_precision_check/heavy_pay_at_exactly_fifty_pounds
    """
    world = _fifty_pound_batch(api)
    fx.deliver(api, world["batch"]["id"], world["shopper"]["id"])

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, total_units=5)
    assert_one_decimal(batch["total_weight_lb"], 50.0, "total_weight_lb")
    assert_one_decimal(batch["total_distance_mi"], 5.0, "total_distance_mi")

    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert payout["heavy_pay_cents"] == 300, (
        "expected the inclusive 50.0 lb tier to pay 300, got "
        f"{payout['heavy_pay_cents']}"
    )
    assert_fields(payout, base_pay_cents=825, mileage_bonus_cents=0)


def test_the_per_unit_guarantee_floor_does_not_lift_a_heavy_batch(api):
    """PRD 3.8: "The guarantee floor is 80 cents multiplied by the batch's
    `total_units`. `guarantee_top_up_cents` is the guarantee floor minus that
    subtotal, using 0 whenever the difference is negative" and at delivery
    "`completed_batch_count` rises by 1, `committed_units` falls by the batch's
    `total_units`".

    825 + 300 + 0 + 0 already exceeds the 80 * 5 = 400 floor, so the top-up is 0
    and the total is 1125.

    Design: Difficulty/boundary_precision_check/heavy_pay_at_exactly_fifty_pounds
    """
    world = _fifty_pound_batch(api)
    shopper_id = world["shopper"]["id"]
    fx.deliver(api, world["batch"]["id"], shopper_id)

    payout = payout_for_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(payout, guarantee_top_up_cents=0, total_payout_cents=1125)

    shopper = read_shopper(api, shopper_id, make_shopper_headers(shopper_id))
    assert_fields(shopper, committed_units=0, completed_batch_count=1)


def _too_small_vehicle_world(api):
    """Batch B10 needs 5 units; the only shopper in the area can carry 4."""
    fx.set_clock(api, CLOCK_0800)
    retailer = fx.make_retailer(api, catalog_markup_pct=0.15)
    r1 = retailer["id"]
    i1 = fx.make_catalog_item_each(
        api, r1, sku="SKU-EACH-EBT", name="Canned Beans",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    shopper = fx.make_shopper(
        api, display_name="Nia Blake", service_area_code="SF-05", vehicle_capacity_units=4
    )
    order = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=4.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, order["id"], c1, i1["id"], 5)
    fx.submit_order(api, order["id"], c1)
    batch = fx.make_batch(
        api, service_area_code="SF-05",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor="PROBATION",
    )
    fx.attach_order(api, batch["id"], order["id"])
    return {"batch": batch, "order": order, "shopper": shopper}


def test_a_capacity_filter_that_empties_the_pool_reports_selector_exhaustion(api):
    """PRD 3.5: a shopper is a candidate only if "their `committed_units` plus the
    batch's `total_units` is less than or equal to their `vehicle_capacity_units`"
    and "If the candidate set is empty the batch is left exactly as it was and the
    request is rejected with `ERR_NO_ELIGIBLE_SHOPPER` (422)."

    0 + 5 > 4 removes the area's only shopper, so the pool is empty on a batch
    that is otherwise perfectly dispatchable.

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_zero_eligible
    """
    world = _too_small_vehicle_world(api)
    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(batch, total_units=5)
    assert_fields(
        read_shopper(api, world["shopper"]["id"], ADMIN_HEADERS),
        vehicle_capacity_units=4,
        committed_units=0,
    )

    validate_error(
        api.dispatch_batch(world["batch"]["id"], ADMIN_HEADERS),
        ERR_NO_ELIGIBLE_SHOPPER,
        422,
    )


def test_a_failed_dispatch_leaves_the_batch_exactly_as_it_was(api):
    """PRD 3.5: "the batch is left exactly as it was" on selector exhaustion, and
    PRD 3.4 gives a fresh batch "an empty `declined_shopper_ids` array, and both
    `offered_shopper_id` and `claimed_shopper_id` null".

    No offer was made, so nothing may be recorded: the batch stays BUILDING, no
    `offer_expires_at` is stamped, and a failed dispatch declines nobody.

    Design: Difficulty/boundary_precision_check/dispatch_empty_candidate_pool_zero_eligible
    """
    world = _too_small_vehicle_world(api)
    api.dispatch_batch(world["batch"]["id"], ADMIN_HEADERS)

    batch = read_batch(api, world["batch"]["id"], ADMIN_HEADERS)
    assert_fields(
        batch,
        status=BATCH_BUILDING,
        offered_shopper_id=None,
        declined_shopper_ids=[],
    )
    assert_null_instant(batch, "offer_expires_at")
