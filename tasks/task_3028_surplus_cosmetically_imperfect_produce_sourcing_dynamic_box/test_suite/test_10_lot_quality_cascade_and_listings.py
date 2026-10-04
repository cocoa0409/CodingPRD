"""The lot-quality investigation cascade plus the remaining collection reads."""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    ADMIN,
    ApiErrorId,
    ANON,
    build_order,
    make_bid,
    make_center,
    make_customer,
    make_lot,
    make_operator_headers,
    make_supplier,
    make_supplier_headers,
    reset_clock,
    setup_box_scenario,
    setup_center_supplier_lot,
    setup_subscriber,
)
from test_helpers.fixtures import (
    advance_clock,
    award_lot,
    file_claim,
    line_plan,
    make_lot_ready,
    order_items,
    pack_order,
    refresh_lot,
    refresh_order,
    refresh_supplier,
    review_claim,
)


def _award_and_ready(api, lot, supplier):
    make_bid(api, lot["id"], supplier["id"], cost=100,
             quantity=lot["quantity_available"])
    return make_lot_ready(api, award_lot(api, lot), "PASS")


def _investigation_scenario(api, *, email="cas@example.com"):
    """One PASS lot with two sibling QUOTED lots of the same supplier and lane,
    plus a packed order carrying one INCLUDED line from the PASS lot."""
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Four Hop Farms", region="NE")
    primary = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                       procurement_grade="SURPLUS", unit_weight_grams=200,
                       unit_cost_cents=100, quantity_available=200, product_name="CAS1")
    sibling_two = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                           procurement_grade="SURPLUS", unit_weight_grams=200,
                           unit_cost_cents=100, quantity_available=200, product_name="CAS2")
    sibling_three = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                             procurement_grade="SURPLUS", unit_weight_grams=200,
                             unit_cost_cents=100, quantity_available=200, product_name="CAS3")
    primary = _award_and_ready(api, primary, supplier)

    customer, subscription = setup_subscriber(api, region="NE", email=email)
    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    built = build_order(api, order, center, line_plan((primary["id"], 6)))
    packed = pack_order(api, built, center)
    item = [i for i in order_items(api, packed) if i["status"] == "INCLUDED"][0]

    return {
        "center": center, "supplier": supplier, "primary": primary,
        "siblings": [sibling_two, sibling_three], "order": packed, "item": item,
    }


def _plus_days(iso, days):
    from datetime import datetime, timedelta

    base = datetime.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
    return (base + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _drive_to_under_review(api, scenario):
    """Uphold a first claim, then escalate a second one to UNDER_REVIEW."""
    order, item = scenario["order"], scenario["item"]
    first = file_claim(api, order, item["id"], reason_code="SPOILED",
                       photo_url="https://cdn.example.com/evo/first.jpg",
                       requested_credit_cents=500)
    review_claim(api, first, "UPHELD")

    # The escalation window is measured against the cited build item's own
    # created_at, which the build stamped at the clock's current reading — the
    # build's opening ready_deadline — so the clock must clear a full seven
    # days past that instant. Reading the far build_deadline would already sit
    # eight days out and leave the claim too young to escalate.
    built_at = get_success_data(api.get_box_order(order["id"], ADMIN))["ready_deadline"]
    escalation_instant = _plus_days(built_at, 8)
    advance_clock(api, escalation_instant)
    second = file_claim(api, order, item["id"], reason_code="SPOILED",
                        photo_url="https://cdn.example.com/evo/second.jpg",
                        requested_credit_cents=300)
    second = review_claim(api, second, "REJECTED")
    return first, second


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------
def test_second_claim_rejection_expires_the_sibling_lots_of_the_supplier(api):
    """PRD §3.1: "every lot belonging to the same supplier and the same lane
    whose procurement `status` is still `QUOTED` or `AWARDED` is expired at the
    same moment, and those expirations feed straight back into the supplier's
    reliability score."
    PRD §3.3: "A rejected outcome there requires the cited lot's
    `quality_status` to be `INVESTIGATION`, and it leaves `credited_cents` at
    zero, drives the lot's `quality_status` to its terminal `REJECTED`"

    Design: Difficulty/transitive_cascade/quality_investigation_cascade_lot_expiry_to_supplier_score
    """
    scenario = _investigation_scenario(api)
    primary, siblings = scenario["primary"], scenario["siblings"]
    _, second = _drive_to_under_review(api, scenario)

    assert second["status"] == "UNDER_REVIEW"
    assert refresh_lot(api, primary)["quality_status"] == "INVESTIGATION"

    # A rejection from UNDER_REVIEW is the terminal outcome: it drives the cited
    # lot to REJECTED, and that is the event that expires the supplier's
    # still-open lots in the same lane.
    terminal = review_claim(api, second, "REJECTED")
    assert terminal["status"] == "REJECTED"
    assert refresh_lot(api, primary)["quality_status"] == "REJECTED"
    for sibling in siblings:
        assert refresh_lot(api, sibling)["status"] == "EXPIRED"

    supplier = refresh_supplier(api, scenario["supplier"])
    assert supplier["lots_awarded_total"] == 1
    assert supplier["lots_accepted_total"] == 1
    assert supplier["claims_upheld_total"] == 1


def test_the_cascade_recomputes_the_lane_open_claim_count(api):
    """PRD §2.7: "The separate `open_claim_count` field on the same center
    counts `QualityClaim` rows at that center whose status is `IN_REVIEW` or
    `UNDER_REVIEW`; it is a reported derived figure and does not move the posture."
    PRD §3.1: "Every one of these quality transitions also recomputes the lane's
    open claim count, which in turn refreshes that center's forward posture."

    Design: Difficulty/transitive_cascade/quality_investigation_cascade_lot_expiry_to_supplier_score
    """
    scenario = _investigation_scenario(api, email="cas2@example.com")
    center, primary = scenario["center"], scenario["primary"]
    _drive_to_under_review(api, scenario)

    center_read = get_success_data(api.get_fulfillment_center(center["id"], ADMIN))
    # The upheld claim is closed out; the escalated one is the single open row.
    assert center_read["open_claim_count"] == 1
    assert refresh_lot(api, primary)["quality_status"] == "INVESTIGATION"
    # The posture is driven by the counter alone, which never moved.
    assert center_read["forward_posture"] == "OPEN"


# ---------------------------------------------------------------------------
# Collections: filtering and pagination
# ---------------------------------------------------------------------------
def test_box_orders_list_paginates_over_the_whole_filtered_set(api):
    """PRD §2.3: "List responses publish four pagination fields in the `meta`
    object of the response envelope: `limit`, `offset`, `total_count` and `has_more`."
    PRD §2.3: "The `total_count` is the number of rows matching the filter
    before pagination is applied, and `has_more` reports whether at least one
    matching row exists beyond the returned window."

    Design: Corner/entities/box_orders_list_paginates_and_reports_total_count_and_has_more
    """
    scenario = setup_box_scenario(
        api, cycles=(2, 3, 4),
        lot_overrides={"category": "FRUIT", "unit_weight_grams": 100,
                       "unit_cost_cents": 100, "quantity_available": 300},
    )
    center = scenario["center"]
    customer = scenario["customer"]

    first_page = api.list_box_orders(ADMIN, {"fulfillment_center_id": center["id"],
                                             "limit": 2, "offset": 0})
    rows, meta = validate_paginated(first_page)
    assert len(rows) == 2
    assert meta["total_count"] == 3
    assert meta["limit"] == 2
    assert meta["offset"] == 0
    assert meta["has_more"] is True

    second_page = api.list_box_orders(ADMIN, {"fulfillment_center_id": center["id"],
                                              "limit": 2, "offset": 2})
    rows_two, meta_two = validate_paginated(second_page)
    assert len(rows_two) == 1
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False

    filtered = api.list_box_orders(ADMIN, {"customer_id": customer["id"]})
    rows_three, _ = validate_paginated(filtered)
    assert len(rows_three) == 1

    defaulted = api.list_box_orders(ADMIN, {"fulfillment_center_id": center["id"]})
    rows_four, meta_four = validate_paginated(defaulted)
    assert len(rows_four) == 3
    assert meta_four["limit"] == 10
    assert meta_four["offset"] == 0


def test_customer_list_filters_by_service_region_and_home_center(api):
    """PRD §2.6: "When a customer is registered without an explicit
    `home_fulfillment_center_id`, the platform assigns one: the eligible set is
    every `FulfillmentCenter` whose `is_active` flag is true and whose `region`
    equals the customer's `service_region`, that set is ranked by `code` ascending"
    PRD §4: "| GET | `/produce/customers` | List subscribers, optionally
    filtered by home center or service region | PlatformAdmin |"

    Design: Corner/entities/customer_list_filters_by_home_center_and_service_region
    """
    reset_clock(api)
    so_center = make_center(api, code="DEMO-SO", region="SO", max_concurrent_building_cycles=5)
    ne_center = make_center(api, code="LGF-NE", region="NE", max_concurrent_building_cycles=5)
    so_customer, so_sub = setup_subscriber(api, region="SO", email="lg@example.com")
    ne_customer, ne_sub = setup_subscriber(api, region="NE", email="lh@example.com")

    by_region = validate_paginated(api.list_customers(ADMIN, {"service_region": "SO"}))
    rows, _ = by_region
    assert len(rows) == 1
    assert rows[0]["id"] == so_customer["id"]

    by_center = validate_paginated(
        api.list_customers(ADMIN, {"home_fulfillment_center_id": so_center["id"]})
    )
    rows_center, _ = by_center
    assert len(rows_center) == 1
    assert rows_center[0]["id"] == so_customer["id"]

    empty_rows, empty_meta = validate_paginated(
        api.list_customers(ADMIN, {"service_region": "WE"})
    )
    assert len(empty_rows) == 0
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    all_rows, _ = validate_paginated(api.list_customers(ADMIN))
    assert len(all_rows) == 2


def test_sourcing_bid_list_filters_by_lot_and_status(api):
    """PRD §3.2: "Bids are grouped by lot, and a lot's bid set is the pool that
    the sourcing allocation works over."
    PRD §4: "| GET | `/produce/sourcing-bids` | List sourcing bids, optionally
    filtered | PlatformAdmin |"

    Design: Corner/entities/sourcing_bid_list_filters_by_status_and_lot
    """
    reset_clock(api)
    center = make_center(api, code="DEMO-NE", region="NE", max_concurrent_building_cycles=5)
    supplier = make_supplier(api, name="Supply Co BL", region="NE")
    lot = make_lot(api, supplier["id"], center["id"], category="FRUIT",
                   procurement_grade="SURPLUS", unit_weight_grams=100,
                   unit_cost_cents=100, quantity_available=300)

    make_bid(api, lot["id"], supplier["id"], cost=100, quantity=300)
    lot = award_lot(api, lot)
    extra = make_bid(api, lot["id"], supplier["id"], cost=150, quantity=100)
    validate_success(
        api.withdraw_bid(extra["id"], {}, make_supplier_headers(supplier["id"])),
        200,
    )

    withdrawn = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "WITHDRAWN"})
    )
    assert len(withdrawn) == 1
    selected = get_success_data(
        api.list_bids(ADMIN, {"supply_lot_id": lot["id"], "status": "SELECTED"})
    )
    assert len(selected) == 1
    by_supplier = get_success_data(api.list_bids(ADMIN, {"supplier_id": supplier["id"]}))
    assert len(by_supplier) == 2


# ---------------------------------------------------------------------------
# The logical clock endpoint
# ---------------------------------------------------------------------------
def test_clock_endpoint_reads_back_the_value_it_was_set_to(api):
    """PRD §2.4: "Before any clock-setting call is made, that clock reads
    exactly `2026-09-01T00:00:00Z`"
    PRD §2.4: "An administrator advances or rewinds the clock by supplying a
    `to_iso8601` instant, and the call reports the resulting value back as
    `current_utc`."

    Design: Corner/endpoints/clock_endpoint_reads_back_the_value_it_was_set_to
    """
    reset_clock(api, "2026-09-05T00:00:00Z")
    moved = validate_success(api.set_clock({"to_iso8601": "2026-09-05T00:00:00Z"}, ADMIN), 200)
    assert moved["current_utc"].startswith("2026-09-05T00:00:00")

    back = validate_success(
        api.set_clock({"to_iso8601": "2026-09-01T00:00:00Z"}, ADMIN), 200
    )
    assert back["current_utc"].startswith("2026-09-01T00:00:00")

    make_center(api, code="CLOCK-NE", region="NE")
    customer = make_customer(api, email="clock@example.com", full_name="Clock Cee",
                             service_region="NE")
    assert customer["created_at"].startswith("2026-09-01T00:00:00")


# ---------------------------------------------------------------------------
# Re-pinning a region's subscribers
# ---------------------------------------------------------------------------
def test_deactivating_a_center_repins_the_regions_subscribers(api):
    """PRD §2.6: "updating a fulfillment center's configuration re-evaluates
    the assignment for every `Customer` of that center's region, so a center
    turned inactive, or added to a region, immediately re-spreads that region's
    subscribers."
    PRD §2.6: "Whenever a customer's home center changes by any means, every
    `Subscription` belonging to that customer is re-pinned to the same new center"

    Design: Corner/endpoints/center_update_repins_the_regions_subscribers_to_the_new_winner
    """
    reset_clock(api)
    aaa = make_center(api, code="AAA-NE", region="NE", max_concurrent_building_cycles=5)
    zzz = make_center(api, code="ZZZ-NE", region="NE", max_concurrent_building_cycles=5)
    customer, subscription = setup_subscriber(api, region="NE", email="repin@example.com")
    assert customer["home_fulfillment_center_id"] == aaa["id"]

    updated = validate_success(
        api.update_fulfillment_center(
            aaa["id"],
            {"is_active": False, "expected_fulfillment_center_version": aaa["version"]},
            ADMIN,
        ),
        200,
    )
    assert updated["is_active"] is False

    customer_read = get_success_data(api.get_customer(customer["id"], ADMIN))
    assert customer_read["home_fulfillment_center_id"] == zzz["id"]
    subscription_read = get_success_data(api.get_subscription(subscription["id"], ADMIN))
    assert subscription_read["home_fulfillment_center_id"] == zzz["id"]

    order = get_success_data(
        api.create_box_order(
            {"customer_id": customer["id"], "subscription_id": subscription["id"],
             "serving_cycle_index": 2, "cuisine_preference": "STANDARD"},
            ADMIN,
        )
    )
    assert order["fulfillment_center_id"] == zzz["id"]
    assert len(get_success_data(api.list_center_customers(zzz["id"], ADMIN))) == 1