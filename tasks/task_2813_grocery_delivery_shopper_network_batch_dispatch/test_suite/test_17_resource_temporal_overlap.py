"""Difficulty rule resource_temporal_overlap.

Two contended resources with deliberately opposite interval semantics: a
shopper's time is half-open with a 15-minute buffer on the END of a held
interval, while a retailer's aisle capacity is a closed-interval AGGREGATE
count against `concurrent_shopper_cap`.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_RETAILER_CONCURRENCY_CAP_REACHED,
    ERR_SHOPPER_CAPACITY_EXCEEDED,
    ERR_SHOPPER_WINDOW_CONFLICT,
)
from test_helpers.assertions import (
    assert_fields,
    assert_instant_field,
    assert_total_count,
    read_batch,
    read_order,
    read_shopper,
    single_row,
)
from test_helpers.constants import (
    BATCH_BUILDING,
    BATCH_CLAIMED,
    BATCH_OFFERED,
    CLOCK_0800,
    FULFILLMENT_IN_BATCH,
    FULFILLMENT_PLACED,
    TIER_PROBATION,
)
from test_helpers.test_users import ADMIN_HEADERS, make_shopper_headers


def _two_window_world(api, second_window_start):
    """One shopper, one held batch [08:00, 11:15), one standing offer to test."""
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
        api, display_name="Ivy Chen", service_area_code="SF-07",
        vehicle_capacity_units=10,
    )
    sw = shopper["id"]

    ow1 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T11:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, ow1["id"], c1, i1["id"], 1)
    fx.submit_order(api, ow1["id"], c1)
    ow2 = fx.make_draft_order(
        api, c1, r1, delivery_distance_mi=3.0,
        delivery_deadline="2026-08-01T13:00:00Z",
        ebt_requested=False, tip_amount_cents=0,
    )
    fx.add_line_each(api, ow2["id"], c1, i1["id"], 1)
    fx.submit_order(api, ow2["id"], c1)

    bw1 = fx.make_batch(
        api, service_area_code="SF-07",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T11:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, bw1["id"], ow1["id"])
    bw2 = fx.make_batch(
        api, service_area_code="SF-07",
        shop_window_start=second_window_start,
        shop_window_end="2026-08-01T13:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, bw2["id"], ow2["id"])
    fx.dispatch(api, bw1["id"])
    fx.dispatch(api, bw2["id"])
    claimed = fx.claim(api, bw1["id"], sw)
    return {
        "shopper": shopper,
        "bw1": bw1,
        "bw2": bw2,
        "claimed": claimed,
    }


def test_the_turnaround_buffer_alone_makes_the_second_window_collide(api):
    """PRD 3.5: "Each batch the shopper already holds ... occupies a half-open
    interval that begins at *its* `shop_window_start` and ends 15 minutes after
    *its* `delivery_deadline`. The 15-minute turnaround buffer is applied to the
    **end** of the held interval only" and "A conflict exists when the candidate
    interval's start is strictly before the held interval's end **and** the held
    interval's start is strictly before the candidate interval's end."

    BW1 is held as [08:00, 11:00 + 15 min) = [08:00, 11:15) and BW2's candidate
    interval is [11:10, 13:00); 11:10 < 11:15 and 08:00 < 13:00, so the claim is
    refused with `ERR_SHOPPER_WINDOW_CONFLICT` (409). It is not the capacity
    gate: 1 committed + 1 unit = 2 is well inside the 10-unit vehicle.

    Design: Difficulty/resource_temporal_overlap/shopper_window_half_open_with_turnaround_buffer
    """
    world = _two_window_world(api, "2026-08-01T11:10:00Z")
    sw = world["shopper"]["id"]
    held = world["claimed"]
    assert_fields(held, status=BATCH_CLAIMED, claimed_shopper_id=sw)
    assert_instant_field(held, "delivery_deadline", "2026-08-01T11:00:00Z")

    refused = api.claim_batch(world["bw2"]["id"], make_shopper_headers(sw))
    error = validate_error(refused, ERR_SHOPPER_WINDOW_CONFLICT, 409)
    assert error["error_id"] != ERR_SHOPPER_CAPACITY_EXCEEDED, (
        "the temporal rule must answer, not the capacity rule: "
        f"got {error['error_id']}"
    )


def test_a_start_at_exactly_the_buffered_end_is_claimable(api):
    """PRD 3.5: "Both comparisons are strict, so two raw intervals that abut
    exactly are legal, but a gap shorter than the 15-minute turnaround is not."
    PRD 3.5 also fixes what a refused claim may not do: "A successful claim moves
    the batch from `OFFERED` to `CLAIMED` ... re-derives the shopper's
    `committed_units` — which rises by the batch's `total_units`".

    With BW2 starting at 11:10 the refusal must leave the offer standing and the
    capacity ledger at the single unit BW1 holds. Moving the start to exactly
    11:15 makes the candidate start equal to the held end, and strict `<` lets
    the same claim through, taking `committed_units` to 2.

    Design: Difficulty/resource_temporal_overlap/shopper_window_half_open_with_turnaround_buffer
    """
    refused_world = _two_window_world(api, "2026-08-01T11:10:00Z")
    sw = refused_world["shopper"]["id"]
    shopper_headers = make_shopper_headers(sw)
    api.claim_batch(refused_world["bw2"]["id"], shopper_headers)

    untouched = read_batch(api, refused_world["bw2"]["id"], ADMIN_HEADERS)
    assert_fields(
        untouched,
        status=BATCH_OFFERED,
        offered_shopper_id=sw,
        claimed_shopper_id=None,
    )
    shopper = read_shopper(api, sw, shopper_headers)
    assert_fields(shopper, committed_units=1)

    control = _two_window_world(api, "2026-08-01T11:15:00Z")
    control_sw = control["shopper"]["id"]
    claimed = validate_success(
        api.claim_batch(control["bw2"]["id"], make_shopper_headers(control_sw))
    )
    assert_fields(claimed, status=BATCH_CLAIMED, claimed_shopper_id=control_sw)
    shopper = read_shopper(api, control_sw, make_shopper_headers(control_sw))
    assert_fields(shopper, committed_units=2)


def _store_cap_world(api, dispatch_first_neighbour):
    """Retailer R7 (cap 2) with two neighbour batches around a BUILDING target."""
    fx.set_clock(api, CLOCK_0800)
    # The store code is left to the factory's unique default: PRD 3.1 makes it
    # unique across all retailer rows and this builder runs twice per test.
    retailer = fx.make_retailer(
        api,
        legal_name="Sunset Grocery Group",
        catalog_markup_pct=0.15,
        concurrent_shopper_cap=2,
    )
    r7 = retailer["id"]
    i7 = fx.make_catalog_item_each(
        api, r7, sku="SKU-CAP-01", name="Pasta Box",
        in_store_price_cents=400, is_ebt_eligible=True, unit_weight_lb=1.0,
    )
    customer = fx.make_customer(api)
    c1 = customer["id"]
    fx.make_shopper(
        api, display_name="Rico Vega", service_area_code="SF-08",
        vehicle_capacity_units=10,
    )

    def _order(deadline):
        order = fx.make_draft_order(
            api, c1, r7, delivery_distance_mi=2.0,
            delivery_deadline=deadline,
            ebt_requested=False, tip_amount_cents=0,
        )
        fx.add_line_each(api, order["id"], c1, i7["id"], 1)
        fx.submit_order(api, order["id"], c1)
        return order

    oa = _order("2026-08-01T10:00:00Z")
    ob = _order("2026-08-01T12:00:00Z")
    ot = _order("2026-08-01T12:00:00Z")

    ba = fx.make_batch(
        api, service_area_code="SF-08",
        shop_window_start="2026-08-01T08:00:00Z",
        shop_window_end="2026-08-01T10:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, ba["id"], oa["id"])
    bb = fx.make_batch(
        api, service_area_code="SF-08",
        shop_window_start="2026-08-01T10:00:00Z",
        shop_window_end="2026-08-01T12:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    fx.attach_order(api, bb["id"], ob["id"])
    if dispatch_first_neighbour:
        fx.dispatch(api, ba["id"])
    fx.dispatch(api, bb["id"])
    bt = fx.make_batch(
        api, service_area_code="SF-08",
        shop_window_start="2026-08-01T10:00:00Z",
        shop_window_end="2026-08-01T12:00:00Z",
        tier_access_floor=TIER_PROBATION,
    )
    target = read_batch(api, bt["id"], ADMIN_HEADERS)
    return {
        "ba": ba,
        "bb": bb,
        "target": target,
        "ot": ot,
        "customer": customer,
    }


def test_two_closed_interval_neighbours_reach_the_store_cap(api):
    """PRD 3.4: "count every batch other than the target batch whose `status` is
    `OFFERED`, `CLAIMED`, or `SHOPPING`, which already carries at least one
    member order for that same retailer, and whose shopping window intersects the
    target batch's shopping window. The intersection test here uses **closed**
    intervals ... so windows that merely touch at an endpoint do collide. ... If
    that count has reached the retailer's `concurrent_shopper_cap` or exceeds it,
    the attachment is rejected with `ERR_RETAILER_CONCURRENCY_CAP_REACHED`
    (409)."

    BA 08:00-10:00 touches the target's 10:00 start and BB 10:00-12:00 overlaps
    it outright, so the count is 2, which has reached the cap of 2.

    Design: Difficulty/resource_temporal_overlap/retailer_closed_interval_aggregate_cap
    """
    world = _store_cap_world(api, dispatch_first_neighbour=True)
    assert_fields(read_batch(api, world["ba"]["id"], ADMIN_HEADERS), status=BATCH_OFFERED)
    assert_fields(read_batch(api, world["bb"]["id"], ADMIN_HEADERS), status=BATCH_OFFERED)

    target = world["target"]
    refused = api.add_order_to_batch(
        target["id"],
        f.batch_order_payload(world["ot"]["id"], target["version"]),
        ADMIN_HEADERS,
    )
    validate_error(refused, ERR_RETAILER_CONCURRENCY_CAP_REACHED, 409)


def test_the_capped_attachment_writes_nothing_and_an_idle_neighbour_never_counts(api):
    """PRD 3.4: "When all gates pass, the membership row is created and returned,
    the batch's composition is re-derived, the order's `fulfillment_status` moves
    from `PLACED` to `IN_BATCH`, and the batch's `version` increases by 1." PRD
    3.4 also excludes the idle neighbours: "Batches in `BUILDING`, `DELIVERED`,
    or `ABANDONED` are ignored entirely."

    The refused attachment must leave no membership row, no aggregate movement
    and no version bump, and the order must still be `PLACED`. Leaving BA in
    `BUILDING` drops the collision count to 1, which is below the cap of 2, and
    the identical attachment succeeds — proving the rule counts an aggregate
    rather than vetoing each pairwise overlap.

    Design: Difficulty/resource_temporal_overlap/retailer_closed_interval_aggregate_cap
    """
    world = _store_cap_world(api, dispatch_first_neighbour=True)
    target = world["target"]
    api.add_order_to_batch(
        target["id"],
        f.batch_order_payload(world["ot"]["id"], target["version"]),
        ADMIN_HEADERS,
    )
    assert_total_count(api.list_batch_orders_of_batch(target["id"], ADMIN_HEADERS), 0)
    after = read_batch(api, target["id"], ADMIN_HEADERS)
    assert_fields(
        after,
        status=BATCH_BUILDING,
        total_units=0,
        store_count=0,
        version=target["version"],
    )
    order = read_order(api, world["ot"]["id"], ADMIN_HEADERS)
    assert_fields(order, fulfillment_status=FULFILLMENT_PLACED)

    control = _store_cap_world(api, dispatch_first_neighbour=False)
    assert_fields(
        read_batch(api, control["ba"]["id"], ADMIN_HEADERS), status=BATCH_BUILDING
    )
    control_target = control["target"]
    membership = validate_success(
        api.add_order_to_batch(
            control_target["id"],
            f.batch_order_payload(control["ot"]["id"], control_target["version"]),
            ADMIN_HEADERS,
        ),
        201,
    )
    assert_fields(membership, batch_id=control_target["id"], sequence_no=1, units=1)
    assert_fields(
        read_batch(api, control_target["id"], ADMIN_HEADERS),
        total_units=1,
        store_count=1,
    )
    assert_fields(
        read_order(api, control["ot"]["id"], ADMIN_HEADERS),
        fulfillment_status=FULFILLMENT_IN_BATCH,
    )
    row = single_row(api.list_batch_orders_of_order(control["ot"]["id"], ADMIN_HEADERS))
    assert_fields(row, batch_id=control_target["id"])
