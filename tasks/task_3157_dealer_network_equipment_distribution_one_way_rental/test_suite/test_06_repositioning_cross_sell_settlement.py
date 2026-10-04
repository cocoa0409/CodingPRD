"""Repositioning costs and driver gates, cross-sell bundle math and zone
capacity, quarterly dealer settlement, allocation rounds, and RBAC."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    create_location_payload,
    create_quoted_reservation,
    make_customer_headers,
    make_dealer_agent_headers,
    make_driver_headers,
    make_finance_headers,
    setup_active_rate,
    setup_agreement,
    setup_customer,
    setup_dealer,
    setup_location,
    setup_two_locations,
    setup_unit,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Dealer / location / unit lifecycle and listing
# ---------------------------------------------------------------------------

def test_create_location_returns_201_with_defaults():
    """PRD §3.1: "Each site is registered with a unique `location_code`, a
    `city`, a `geo_zone`, and a non-negative `storage_capacity` counting the
    self-storage units at that site; the zone value drives both the
    reassignment search radius and the storage capacity pool, and a new
    location opens in the `OPEN` state."
    PRD §4: "Creating a new resource returns 201; every other successful
    operation — modifications, state transitions, reads, previews, reports —
    returns 200."

    Design: Corner/entities/create_location_returns_201_with_defaults
    """
    resp = api_client.create_location(
        create_location_payload(location_code="PHX-C1", geo_zone="NORTH",
                                storage_capacity=10),
        TEST_USERS["admin"])
    loc = validate_success(resp, expected_status=201)
    assert loc["status"] == "OPEN"
    assert loc["version"] == 1
    assert isinstance(loc["id"], str) and loc["id"]


def test_create_dealer_missing_required_field_returns_invalid_request():
    """PRD §2.8: "A missing required field, a value of the wrong type, or an
    unknown enum value anywhere in a request is `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §3.1: "Dealers are then attached to sites: a dealer record carries a
    unique `dealer_code`, a business `name`, the `location_id` of the site it
    operates, and optionally a `commission_rate_override` — a decimal between 0
    and 1 that, when present, replaces the lane rate's commission for every
    settlement quarter; when null, the lane's own rate applies."

    Design: Corner/entities/create_dealer_missing_required_field_returns_invalid_request
    """
    loc = setup_location()
    resp = api_client.create_dealer(
        {"name": "No Code Dealer", "location_id": loc["id"]},
        TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_duplicate_natural_key_returns_duplicate_resource():
    """PRD §2.10: "Several entities carry human-meaningful natural keys that
    must be globally unique across their collection: a dealer's `dealer_code`
    (for example UH-4821), a location's `location_code` (for example PHX-07), a
    unit's `unit_code`, and a customer's `email`. Two singleton-per-parent
    constraints also hold: at most one `RentalAgreement` may exist for a given
    `reservation_id`, and at most one `DamageProtectionPlan` may exist for a
    given `agreement_id`. A creation that collides on any of these keys is
    rejected with `ERR_DUPLICATE_RESOURCE` (HTTP 409)."

    Design: Corner/entities/duplicate_natural_key_returns_duplicate_resource
    """
    setup_location(code_prefix="DUP")
    resp = api_client.create_location(
        create_location_payload(geo_zone="SOUTH", storage_capacity=5),
        TEST_USERS["admin"])
    # Force the same location_code as the first call produced.
    # (factory generates unique codes; reuse an explicit code instead)
    first = setup_location(code_prefix="PHX-C3")
    resp = api_client.create_location(
        {"location_code": first["location_code"], "city": "Phoenix",
         "geo_zone": "SOUTH", "storage_capacity": 5},
        TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESOURCE, expected_status=409)


def test_invalid_enum_value_rejected():
    """PRD §2.8: "A missing required field, a value of the wrong type, or an
    unknown enum value anywhere in a request is `ERR_INVALID_REQUEST`
    (HTTP 400)."
    PRD §2.9: "Shared vocabularies: equipment categories are `TRUCK_10FT`,
    `TRUCK_15FT`, `TRUCK_26FT`, `TRAILER_4X8`, `TRAILER_6X12`, and `TOW_DOLLY`;
    geographic zones are `NORTH`, `SOUTH`, `EAST`, `WEST`, and `CENTRAL`;
    seasons are `PEAK`, `SHOULDER`, and `OFF_PEAK`; hitch classes are
    `CLASS_I`, `CLASS_II`, `CLASS_III`, `CLASS_IV`, and `NONE`; rental kinds
    are `ROUND_TRIP` and `ONE_WAY`; protection tiers are `BASIC`, `STANDARD`,
    and `PREMIUM`; a reservation's `tow_check_result` is `PASS`, `FAIL`, or
    `NOT_REQUIRED`."

    Design: Corner/entities/invalid_enum_value_rejected
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    resp = api_client.create_equipment_unit(
        {"unit_code": "U-C4", "equipment_type": "TRUCK_99FT",
         "dealer_id": dealer["id"]},
        TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)


def test_get_nonexistent_entity_returns_not_found():
    """PRD §2.8: "(3) Path existence: every identifier embedded in the URL is
    resolved left-to-right — a dangling path id yields `ERR_NOT_FOUND`
    (HTTP 404)."

    Design: Corner/entities/get_nonexistent_entity_returns_not_found
    """
    resp = api_client.get_dealer(NON_EXISTENT_UUID, TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND, expected_status=404)


def test_list_pagination_envelope_defaults():
    """PRD §2.3: "Every list endpoint accepts `limit` and `offset` as query
    parameters. `limit` defaults to 10, must be at least 1, and may not exceed
    100. `offset` defaults to 0. The `meta` envelope of a list response carries
    `limit`, `offset`, `total_count` (the number of rows matching the filter,
    not just the page), and `has_more` (true when rows exist beyond the
    returned page)."

    Design: Corner/entities/list_pagination_envelope_defaults
    """
    loc = setup_location(code_prefix="PHX-C6")
    for i in range(1, 13):
        setup_dealer(loc, code_prefix=f"D-C6-{i:02d}")
    page1, meta1 = validate_paginated(api_client.list_dealers(TEST_USERS["admin"]))
    assert meta1["limit"] == 10
    assert meta1["offset"] == 0
    assert meta1["total_count"] == 12
    assert meta1["has_more"] is True
    assert len(page1) == 10
    page2, meta2 = validate_paginated(api_client.list_dealers(
        TEST_USERS["admin"], params={"offset": 10}))
    assert len(page2) == 2
    assert meta2["has_more"] is False


def test_unit_maintenance_cycle_guarded_by_owner_dealer():
    """PRD §3.1: "It moves a unit `AVAILABLE → MAINTENANCE` when `to_status` is
    `MAINTENANCE`, and `MAINTENANCE → AVAILABLE` when `to_status` is
    `AVAILABLE` — no other target is reachable through this operation — and in
    both directions the acting `DealerAgent`'s own dealer must be the unit's
    current holding dealer."

    Design: Corner/state_machines/unit_maintenance_cycle_guarded_by_owner_dealer
    """
    loc = setup_location()
    dealer_1 = setup_dealer(loc, code_prefix="D-S5A")
    dealer_2 = setup_dealer(loc, code_prefix="D-S5B")
    unit = setup_unit(dealer_1, code_prefix="U-S5")
    # An agent of another dealer cannot move the unit.
    resp = api_client.set_equipment_unit_status(
        unit["id"], {"to_status": "MAINTENANCE", "status_note": "oil leak"},
        make_dealer_agent_headers(dealer_2["id"]))
    assert resp.status_code in (403, 409), \
        f"expected ownership rejection, got {resp.status_code}: {resp.text}"
    # The owning dealer's agent succeeds.
    updated = validate_success(api_client.set_equipment_unit_status(
        unit["id"], {"to_status": "MAINTENANCE", "status_note": "oil leak"},
        make_dealer_agent_headers(dealer_1["id"])))
    assert updated["status"] == "MAINTENANCE"
    assert updated["status_note"] == "oil leak"


def test_dealer_deactivate_blocked_with_holdings():
    """PRD §3.1: "Dealer deactivation is likewise guarded and terminal: it
    proceeds only from `ACTIVE`, only while no reservation promises fulfilment
    from that dealer (none in `QUOTED`, `CONFIRMED`, or `REASSIGNED`), and only
    while the dealer holds no unit in `AVAILABLE`, `HELD`, or `OUT` — otherwise
    the attempt fails with `ERR_DEALER_HAS_ACTIVE_HOLDINGS`."

    Design: Corner/validations/dealer_deactivate_blocked_with_holdings
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    setup_unit(dealer)
    resp = api_client.deactivate_dealer(dealer["id"], TEST_USERS["admin"])
    validate_error(resp, ApiErrorId.ERR_DEALER_HAS_ACTIVE_HOLDINGS,
                   expected_status=409)
    after = validate_success(api_client.get_dealer(dealer["id"], TEST_USERS["admin"]))
    assert after["status"] == "ACTIVE"


def test_lane_rate_activation_supersedes_conflict():
    """PRD §3.2: "Activation moves a row `DRAFT → ACTIVE` and, in the same act,
    any other row with the identical lane key — same origin, destination,
    equipment type, and season — that was `ACTIVE` becomes `SUPERSEDED`;
    uniqueness of the active rate per lane key is enforced here and nowhere
    else."

    Design: Corner/state_machines/lane_rate_activation_supersedes_conflict
    """
    loc_a, loc_b = setup_two_locations()
    rate_1 = setup_active_rate(loc_a, loc_b, season="PEAK", base_rate_cents=5000,
                               reposition_surcharge_cents=1000)
    from test_helpers import create_lane_rate_payload
    rate_2 = validate_success(api_client.create_lane_rate(
        create_lane_rate_payload(
            origin_location_id=loc_a["id"], dest_location_id=loc_b["id"],
            season="PEAK", base_rate_cents=7000, reposition_surcharge_cents=1000,
            commission_rate=0.12),
        TEST_USERS["pricing"]), expected_status=201)
    validate_success(api_client.activate_lane_rate(rate_2["id"], TEST_USERS["pricing"]))
    incumbent = validate_success(api_client.get_lane_rate(
        rate_1["id"], TEST_USERS["pricing"]))
    challenger = validate_success(api_client.get_lane_rate(
        rate_2["id"], TEST_USERS["pricing"]))
    assert challenger["status"] == "ACTIVE"
    assert incumbent["status"] == "SUPERSEDED"


# ---------------------------------------------------------------------------
# Repositioning
# ---------------------------------------------------------------------------

def test_reposition_task_selector_picks_earliest_created_unit():
    """PRD §3.9: "The system selects the unit itself: among `AVAILABLE` units
    of that type physically at the from-location, the one with the earliest
    `created_at` is chosen, and it moves `AVAILABLE → REPOSITIONING`, with the
    new task's `equipment_unit_id` pointing at it."
    PRD §3.9: "The band table is fixed: identical zones are SHORT at 9000
    cents; the pairs NORTH–SOUTH and EAST–WEST, in either direction, are LONG
    at 52000 cents; every other distinct zone pair is MEDIUM at 24000 cents."

    Design: Corner/endpoints/reposition_task_selector_picks_earliest_created_unit
    """
    loc_a, loc_b = setup_two_locations(zone_a="NORTH", zone_b="SOUTH")
    dealer_a = setup_dealer(loc_a, code_prefix="D-E4A")
    setup_dealer(loc_b, code_prefix="D-E4B")
    u_early = setup_unit(dealer_a, code_prefix="U-E4-EARLY")
    u_late = setup_unit(dealer_a, code_prefix="U-E4-LATE")
    task = validate_success(api_client.create_reposition_task(
        {"from_location_id": loc_a["id"], "to_location_id": loc_b["id"],
         "equipment_type": "TRUCK_10FT"},
        TEST_USERS["admin"]), expected_status=201)
    # Earliest created_at wins, never the id.
    assert task["equipment_unit_id"] == u_early["id"]
    # NORTH->SOUTH is the LONG band: 52000.
    assert task["estimated_reposition_cost_cents"] == 52000
    unit_early = validate_success(api_client.get_equipment_unit(
        u_early["id"], TEST_USERS["admin"]))
    unit_late = validate_success(api_client.get_equipment_unit(
        u_late["id"], TEST_USERS["admin"]))
    assert unit_early["status"] == "REPOSITIONING"
    assert unit_late["status"] == "AVAILABLE"


def test_reposition_complete_cost_includes_idle_penalty():
    """PRD §3.9: "The executed cost, recorded as
    `executed_reposition_cost_cents`, is the band cost plus a flat driver fee
    of 6000 cents, plus an idle penalty of 15000 cents when the unit sat in
    `REPOSITIONING` for more than 48 hours on the logical clock; exactly 48
    hours incurs no penalty."

    Design: Corner/endpoints/reposition_complete_cost_includes_idle_penalty
    """
    loc_a, loc_b = setup_two_locations(zone_a="NORTH", zone_b="SOUTH")
    dealer_a = setup_dealer(loc_a, code_prefix="D-E5A")
    dealer_b = setup_dealer(loc_b, code_prefix="D-E5B")
    setup_unit(dealer_a, code_prefix="U-E5-1")
    setup_unit(dealer_a, code_prefix="U-E5-2")
    validate_success(api_client.set_clock("2026-11-01T00:00:00Z", TEST_USERS["admin"]))
    task_1 = validate_success(api_client.create_reposition_task(
        {"from_location_id": loc_a["id"], "to_location_id": loc_b["id"],
         "equipment_type": "TRUCK_10FT"}, TEST_USERS["admin"]), expected_status=201)
    task_2 = validate_success(api_client.create_reposition_task(
        {"from_location_id": loc_a["id"], "to_location_id": loc_b["id"],
         "equipment_type": "TRUCK_10FT"}, TEST_USERS["admin"]), expected_status=201)
    validate_success(api_client.assign_reposition_task(
        task_1["id"], {"assigned_driver_id": "drv-1"}, TEST_USERS["admin"]))
    validate_success(api_client.assign_reposition_task(
        task_2["id"], {"assigned_driver_id": "drv-2"}, TEST_USERS["admin"]))
    # Complete task 1 at +47h: no penalty (52000 + 6000 = 58000).
    validate_success(api_client.set_clock("2026-11-02T23:00:00Z", TEST_USERS["admin"]))
    done_1 = validate_success(api_client.complete_reposition_task(
        task_1["id"], make_driver_headers("drv-1")))
    assert done_1["executed_reposition_cost_cents"] == 58000
    # Complete task 2 at +49h: penalty applies (52000 + 6000 + 15000 = 73000).
    validate_success(api_client.set_clock("2026-11-03T01:00:00Z", TEST_USERS["admin"]))
    done_2 = validate_success(api_client.complete_reposition_task(
        task_2["id"], make_driver_headers("drv-2")))
    assert done_2["executed_reposition_cost_cents"] == 73000
    # Both units landed at the destination with dealer handoff.
    for task in (done_1, done_2):
        unit = validate_success(api_client.get_equipment_unit(
            task["equipment_unit_id"], TEST_USERS["admin"]))
        assert unit["status"] == "AVAILABLE"
        assert unit["current_location_id"] == loc_b["id"]
        assert unit["current_dealer_id"] == dealer_b["id"]


def test_driver_mismatch_on_task_complete():
    """PRD §3.9: "Completion belongs to the driver alone: the acting
    `X-User-ID` must equal the task's `assigned_driver_id`, else
    `ERR_DRIVER_MISMATCH` (HTTP 403)."

    Design: Corner/validations/driver_mismatch_on_task_complete
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a, code_prefix="D-V7A")
    setup_dealer(loc_b, code_prefix="D-V7B")
    setup_unit(dealer_a, code_prefix="U-V7")
    task = validate_success(api_client.create_reposition_task(
        {"from_location_id": loc_a["id"], "to_location_id": loc_b["id"],
         "equipment_type": "TRUCK_10FT"}, TEST_USERS["admin"]), expected_status=201)
    validate_success(api_client.assign_reposition_task(
        task["id"], {"assigned_driver_id": "driver-1"}, TEST_USERS["admin"]))
    resp = api_client.complete_reposition_task(
        task["id"], make_driver_headers("driver-2"))
    validate_error(resp, ApiErrorId.ERR_DRIVER_MISMATCH, expected_status=403)
    task_after = validate_success(api_client.get_reposition_task(
        task["id"], TEST_USERS["admin"]))
    assert task_after["status"] == "ASSIGNED"


# ---------------------------------------------------------------------------
# Cross-sell orders
# ---------------------------------------------------------------------------

def test_per_line_rounding_then_sum_vs_sum_then_round():
    """PRD §3.10: "The `supplies_subtotal_cents` extends each line at its
    catalogue price times quantity, rounding each line half-up to integer cents
    before summing."
    PRD §3.10: "When the order buys both supplies and storage —
    `storage_months` above zero and a positive supplies subtotal — a bundle
    discount of 10 percent of the supplies subtotal, rounded half-up to integer
    cents, is recorded as `bundle_discount_cents`; otherwise the discount is
    zero. The order's `total_cents` is the supplies subtotal plus the storage
    charge minus the bundle discount."
    PRD §3.10: "The `storage_charge_cents` is the number of months multiplied
    by the monthly storage rate of the dealer's zone: 8900 cents in `NORTH`,
    7900 in `SOUTH`, 9500 in `EAST`, 9900 in `WEST`, and 6900 in `CENTRAL`."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_vs_sum_then_round
    """
    loc = setup_location(geo_zone="NORTH", storage_capacity=100)
    dealer = setup_dealer(loc)
    order = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"],
         "line_items": [{"sku": "BOX_SMALL", "qty": 3}, {"sku": "LOCK", "qty": 1}],
         "storage_months": 7},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    # Per-line: 3*125=375 + 1*1299=1299 -> 1674.
    assert order["supplies_subtotal_cents"] == 1674
    # 7 months * 8900 NORTH rate = 62300.
    assert order["storage_charge_cents"] == 62300
    # Bundle: round_half_up(1674 * 0.10) = 167.
    assert order["bundle_discount_cents"] == 167
    # Total: 1674 + 62300 - 167 = 63807.
    assert order["total_cents"] == 63807


def test_per_line_rounding_bundle_discount_half_up_boundary():
    """PRD §3.10: "When the order buys both supplies and storage —
    `storage_months` above zero and a positive supplies subtotal — a bundle
    discount of 10 percent of the supplies subtotal, rounded half-up to integer
    cents, is recorded as `bundle_discount_cents`; otherwise the discount is
    zero."
    PRD §2.6: "Two rounding disciplines recur and are binding: per-line
    rounding, where each agreement, order, or line item is rounded individually
    and the rounded values are then summed (summing first and rounding once is
    forbidden), and step-order rounding, where a daily rate is rounded before
    being multiplied by a day count, never the reverse."

    Design: Difficulty/combinatorial_formula/per_line_rounding_then_sum_vs_sum_then_round
    """
    loc = setup_location(geo_zone="NORTH", storage_capacity=100)
    dealer = setup_dealer(loc)
    # Subtotal 245 (1 x BOX_LARGE): 10% = 24.5 -> round half up -> 25,
    # distinguishing half-up from floor/truncation at the boundary.
    order = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"],
         "line_items": [{"sku": "BOX_LARGE", "qty": 1}],
         "storage_months": 1},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    assert order["supplies_subtotal_cents"] == 245
    assert order["bundle_discount_cents"] == 25
    assert order["storage_charge_cents"] == 8900
    assert order["total_cents"] == 245 + 8900 - 25


def test_storage_zone_capacity_exactly_full_vs_one_over():
    """PRD §3.10: "Before an order is accepted, the system sums
    `storage_months` over every cross-sell order at locations sharing the
    dealer's `geo_zone`, sums `storage_capacity` over the `OPEN` locations in
    that zone, and rejects the order with `ERR_STORAGE_CAPACITY_EXCEEDED`
    (HTTP 409) when the occupied months plus the new months would exceed the
    pooled capacity — hitting the cap exactly is allowed, only exceeding it
    rejects."

    Design: Difficulty/boundary_precision_check/storage_zone_capacity_exactly_full_vs_one_over
    """
    loc = setup_location(geo_zone="NORTH", storage_capacity=5)
    dealer = setup_dealer(loc)
    validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"], "line_items": [{"sku": "TAPE", "qty": 1}],
         "storage_months": 3},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    # 3 + 2 == 5 == capacity: the boundary is allowed.
    ok = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"], "line_items": [], "storage_months": 2},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    assert ok["storage_charge_cents"] == 17800
    # 5 + 1 > 5: one over the pooled capacity is rejected.
    resp = api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"], "line_items": [], "storage_months": 1},
        make_dealer_agent_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED,
                   expected_status=409)


def test_storage_zone_capacity_boundary_allows_exact_fill_with_supplies():
    """PRD §3.10: "Before an order is accepted, the system sums
    `storage_months` over every cross-sell order at locations sharing the
    dealer's `geo_zone`, sums `storage_capacity` over the `OPEN` locations in
    that zone, and rejects the order with `ERR_STORAGE_CAPACITY_EXCEEDED`
    (HTTP 409) when the occupied months plus the new months would exceed the
    pooled capacity — hitting the cap exactly is allowed, only exceeding it
    rejects."

    Design: Difficulty/boundary_precision_check/storage_zone_capacity_exactly_full_vs_one_over
    """
    loc = setup_location(geo_zone="NORTH", storage_capacity=4)
    dealer = setup_dealer(loc)
    # One order fills the pool exactly.
    filled = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"], "line_items": [{"sku": "TAPE", "qty": 1}],
         "storage_months": 4},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    assert filled["storage_months"] == 4
    # One further storage month exceeds the full pool.
    resp = api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"], "line_items": [{"sku": "TAPE", "qty": 1}],
         "storage_months": 1},
        make_dealer_agent_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED,
                   expected_status=409)


def test_storage_zone_aggregate_capacity_interval_semantics():
    """PRD §3.10: "Storage capacity is pooled at the zone level, not per site."
    PRD §3.10: "Before an order is accepted, the system sums `storage_months`
    over every cross-sell order at locations sharing the dealer's `geo_zone`,
    sums `storage_capacity` over the `OPEN` locations in that zone, and rejects
    the order with `ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 409) when the occupied
    months plus the new months would exceed the pooled capacity — hitting the
    cap exactly is allowed, only exceeding it rejects."

    Design: Difficulty/resource_temporal_overlap/storage_zone_aggregate_capacity_interval_semantics
    """
    loc_1 = setup_location(geo_zone="NORTH", storage_capacity=4, code_prefix="PHX-16")
    loc_2 = setup_location(geo_zone="NORTH", storage_capacity=4, code_prefix="FLG-16")
    dealer_1 = setup_dealer(loc_1, code_prefix="D-161")
    dealer_2 = setup_dealer(loc_2, code_prefix="D-162")
    # Occupy 5 zone-months across the two sites (capacity 8): both succeed.
    validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer_1["id"], "line_items": [], "storage_months": 3},
        make_dealer_agent_headers(dealer_1["id"])), expected_status=201)
    validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer_2["id"], "line_items": [], "storage_months": 2},
        make_dealer_agent_headers(dealer_2["id"])), expected_status=201)
    # Closing L2 shrinks the pool to 4 — only OPEN locations count.
    validate_success(api_client.close_location(loc_2["id"], TEST_USERS["admin"]))
    resp = api_client.create_cross_sell_order(
        {"dealer_id": dealer_1["id"], "line_items": [], "storage_months": 1},
        make_dealer_agent_headers(dealer_1["id"]))
    validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED,
                   expected_status=409)


def test_storage_zone_aggregate_pool_recovers_on_reopen():
    """PRD §3.10: "Storage capacity is pooled at the zone level, not per site."
    PRD §3.10: "Before an order is accepted, the system sums `storage_months`
    over every cross-sell order at locations sharing the dealer's `geo_zone`,
    sums `storage_capacity` over the `OPEN` locations in that zone, and rejects
    the order with `ERR_STORAGE_CAPACITY_EXCEEDED` (HTTP 409) when the occupied
    months plus the new months would exceed the pooled capacity — hitting the
    cap exactly is allowed, only exceeding it rejects."
    PRD §3.1: "Reopening a `CLOSED` location requires nothing further."

    Design: Difficulty/resource_temporal_overlap/storage_zone_aggregate_capacity_interval_semantics
    """
    loc_1 = setup_location(geo_zone="NORTH", storage_capacity=4, code_prefix="AGG-1")
    loc_2 = setup_location(geo_zone="NORTH", storage_capacity=4, code_prefix="AGG-2")
    dealer_1 = setup_dealer(loc_1, code_prefix="D-AG1")
    dealer_2 = setup_dealer(loc_2, code_prefix="D-AG2")
    validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer_1["id"], "line_items": [], "storage_months": 3},
        make_dealer_agent_headers(dealer_1["id"])), expected_status=201)
    validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer_2["id"], "line_items": [], "storage_months": 2},
        make_dealer_agent_headers(dealer_2["id"])), expected_status=201)
    validate_success(api_client.close_location(loc_2["id"], TEST_USERS["admin"]))
    resp = api_client.create_cross_sell_order(
        {"dealer_id": dealer_1["id"], "line_items": [], "storage_months": 1},
        make_dealer_agent_headers(dealer_1["id"]))
    validate_error(resp, ApiErrorId.ERR_STORAGE_CAPACITY_EXCEEDED,
                   expected_status=409)
    # Reopening restores the pooled capacity; the same order now fits (5+1<=8).
    validate_success(api_client.reopen_location(loc_2["id"], TEST_USERS["admin"]))
    ok = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer_1["id"], "line_items": [], "storage_months": 1},
        make_dealer_agent_headers(dealer_1["id"])), expected_status=201)
    assert ok["storage_months"] == 1


def test_computed_field_input_ignored():
    """PRD §3.10: "The `supplies_subtotal_cents` extends each line at its
    catalogue price times quantity, rounding each line half-up to integer cents
    before summing."
    PRD §3.10: "When the order buys both supplies and storage —
    `storage_months` above zero and a positive supplies subtotal — a bundle
    discount of 10 percent of the supplies subtotal, rounded half-up to integer
    cents, is recorded as `bundle_discount_cents`; otherwise the discount is
    zero. The order's `total_cents` is the supplies subtotal plus the storage
    charge minus the bundle discount."

    Design: Corner/entities/computed_field_input_ignored
    """
    loc = setup_location(geo_zone="NORTH")
    dealer = setup_dealer(loc)
    order = validate_success(api_client.create_cross_sell_order(
        {"dealer_id": dealer["id"],
         "line_items": [{"sku": "BOX_SMALL", "qty": 3}, {"sku": "LOCK", "qty": 1}]},
        make_dealer_agent_headers(dealer["id"])), expected_status=201)
    # Server computes: 3*125 + 1*1299 = 1674, no storage, no bundle discount.
    assert order["supplies_subtotal_cents"] == 1674
    assert order["storage_charge_cents"] == 0
    assert order["bundle_discount_cents"] == 0
    assert order["total_cents"] == 1674


# ---------------------------------------------------------------------------
# Quarterly settlement and allocation
# ---------------------------------------------------------------------------

def _run_two_dealer_settlements():
    """Two dealers at A — one with a 0.20 override, one without — each with one
    settled 2-day one-way agreement (total 10000) in 2026-Q4."""
    loc_a, loc_b = setup_two_locations()
    dealer_ovr = setup_dealer(loc_a, commission_rate_override=0.20, code_prefix="D-OVR")
    dealer_lane = setup_dealer(loc_a, code_prefix="D-LANE")
    unit_ovr = setup_unit(dealer_ovr, code_prefix="U-2001")
    unit_lane = setup_unit(dealer_lane, code_prefix="U-2002")
    setup_active_rate(loc_a, loc_b, base_rate_cents=5000, commission_rate=0.10)
    dealer_b = setup_dealer(loc_b, code_prefix="D-DEST")

    def settle_one(dealer, unit, email_prefix, pickup, dropoff, clock_return):
        customer, _ = setup_customer(verify_dealer=dealer, email_prefix=email_prefix)
        rsv = create_confirmed_reservation(
            customer, dealer, loc_b, pickup_date=pickup, dropoff_date=dropoff)
        # checkout_at stamps from the logical clock (PRD §3.7); place it at the
        # pickup instant so the 2-day rental settles at exactly 2 * 5000.
        validate_success(api_client.set_clock(pickup, TEST_USERS["admin"]))
        agreement = validate_success(api_client.create_rental_agreement(
            {"reservation_id": rsv["id"], "equipment_unit_id": unit["id"],
             "return_location_id": loc_b["id"]},
            make_dealer_agent_headers(dealer["id"])), expected_status=201)
        validate_success(api_client.set_clock(clock_return, TEST_USERS["admin"]))
        returned = validate_success(api_client.return_rental_agreement(
            agreement["id"], make_dealer_agent_headers(dealer_b["id"])))
        settled = validate_success(api_client.settle_rental_agreement(
            agreement["id"], {"expected_agreement_version": returned["version"]},
            make_dealer_agent_headers(dealer_b["id"])))
        assert settled["total_settled_cents"] == 10000

    settle_one(dealer_ovr, unit_ovr, "ca",
               "2026-11-10T10:00:00Z", "2026-11-12T10:00:00Z",
               "2026-11-12T10:00:00Z")
    settle_one(dealer_lane, unit_lane, "cb2",
               "2026-11-13T10:00:00Z", "2026-11-15T10:00:00Z",
               "2026-11-15T10:00:00Z")
    return dealer_ovr, dealer_lane


def test_commission_override_vs_lane_rate_variant():
    """PRD §3.11: "The commission pins a rate per agreement: when the dealer's
    `commission_rate_override` is set, that flat rate governs every agreement
    in scope regardless of lane; when it is null, each agreement uses the
    `commission_rate` of the lane rate that was `ACTIVE` at that agreement's
    `checkout_at` for its lane and season, so two agreements with equal totals
    on different lanes contribute different commissions."

    Design: Difficulty/dual_variant_calc/commission_override_vs_lane_rate_variant
    """
    dealer_ovr, dealer_lane = _run_two_dealer_settlements()
    sett_ovr = validate_success(api_client.create_dealer_settlement(
        {"dealer_id": dealer_ovr["id"], "period": "2026-Q4"},
        TEST_USERS["finance"]), expected_status=201)
    sett_lane = validate_success(api_client.create_dealer_settlement(
        {"dealer_id": dealer_lane["id"], "period": "2026-Q4"},
        TEST_USERS["finance"]), expected_status=201)
    assert sett_ovr["gross_rental_cents"] == 10000
    assert sett_lane["gross_rental_cents"] == 10000
    # Flat 0.20 override vs the lane's 0.10 on an identical gross.
    assert sett_ovr["commission_cents"] == 2000
    assert sett_lane["commission_cents"] == 1000
    assert sett_ovr["commission_cents"] != sett_lane["commission_cents"]


def test_commission_override_clawback_and_net():
    """PRD §3.11: "Underperformance has a price: when the dealer's
    `performance_score` is below the floor of 60, a clawback of 10 percent of
    the sum of the two commission figures, rounded half-up, is charged as
    `clawback_cents`; at exactly 60 or above the clawback is zero. `net_cents`
    is the two commissions minus the clawback."
    PRD §3.1: "A dealer is born `ACTIVE`, begins with an `allocated_unit_count`
    of zero, and starts with a `performance_score` of zero until the first
    quarterly review posts."

    Design: Difficulty/dual_variant_calc/commission_override_vs_lane_rate_variant
    """
    dealer_ovr, dealer_lane = _run_two_dealer_settlements()
    sett_ovr = validate_success(api_client.create_dealer_settlement(
        {"dealer_id": dealer_ovr["id"], "period": "2026-Q4"},
        TEST_USERS["finance"]), expected_status=201)
    sett_lane = validate_success(api_client.create_dealer_settlement(
        {"dealer_id": dealer_lane["id"], "period": "2026-Q4"},
        TEST_USERS["finance"]), expected_status=201)
    # Both dealers sit at performance_score 0 (no review posted), below 60.
    assert sett_ovr["clawback_cents"] == 200
    assert sett_ovr["net_cents"] == 1800
    assert sett_lane["clawback_cents"] == 100
    assert sett_lane["net_cents"] == 900


def test_allocation_round_ranks_by_score():
    """PRD §3.11: "Units are dealt in score-descending order, ties broken by
    `created_at` ascending and never by id, until the requested units of each
    type are exhausted; allocated units have their `current_dealer_id`
    reassigned, each affected dealer's `allocated_unit_count` recomputes, and
    the round reports the `allocated` array alongside any
    `skipped_unit_codes` it could not place."
    PRD §3.11: "A `NetworkAdmin` posts quarterly performance reviews in bulk —
    a `period` label such as 2026-Q3 plus the `scores` — and each entry writes
    the dealer's `performance_score`, the figure used both as the reassignment
    ranking key and as an input to allocation; the response reports the
    `updated_dealer_ids` actually touched."

    Design: Corner/endpoints/allocation_round_ranks_by_score
    """
    loc = setup_location(code_prefix="PHX-E6")
    dealer_1 = setup_dealer(loc, code_prefix="D-E6A")
    dealer_2 = setup_dealer(loc, code_prefix="D-E6B")
    dealer_3 = setup_dealer(loc, code_prefix="D-E6C")
    resp = api_client.post_performance_reviews(
        {"period": "2026-Q3", "scores": [
            {"dealer_id": dealer_1["id"], "performance_score": 90},
            {"dealer_id": dealer_2["id"], "performance_score": 90},
            {"dealer_id": dealer_3["id"], "performance_score": 50},
        ]},
        TEST_USERS["admin"])
    assert resp.status_code == 200, f"Setup failed: {resp.text}"
    unit_1 = setup_unit(dealer_3, code_prefix="U-E6-1")
    unit_2 = setup_unit(dealer_3, code_prefix="U-E6-2")
    unit_3 = setup_unit(dealer_3, code_prefix="U-E6-3")
    result = validate_success(api_client.allocate_dealers(
        {"unit_codes": [unit_1["unit_code"], unit_2["unit_code"]]},
        TEST_USERS["admin"]))
    # Score tie at 90: the earlier-created dealer ranks first.
    unit_1_after = validate_success(api_client.get_equipment_unit(
        unit_1["id"], TEST_USERS["admin"]))
    unit_2_after = validate_success(api_client.get_equipment_unit(
        unit_2["id"], TEST_USERS["admin"]))
    unit_3_after = validate_success(api_client.get_equipment_unit(
        unit_3["id"], TEST_USERS["admin"]))
    assert unit_1_after["current_dealer_id"] == dealer_1["id"]
    assert unit_2_after["current_dealer_id"] == dealer_2["id"]
    # The unit not offered in the round stays put.
    assert unit_3_after["current_dealer_id"] == dealer_3["id"]
    for dealer in (dealer_1, dealer_2, dealer_3):
        d = validate_success(api_client.get_dealer(dealer["id"], TEST_USERS["admin"]))
        assert d["allocated_unit_count"] == 1


# ---------------------------------------------------------------------------
# RBAC and validation ladder
# ---------------------------------------------------------------------------

def test_customer_cannot_create_lane_rate():
    """PRD §2.1: "A well-formed request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | /rental-network/lane-rates | Create a lane rate (DRAFT) |
    PricingManager"

    Design: Corner/rbac/customer_cannot_create_lane_rate
    """
    loc_a, loc_b = setup_two_locations()
    resp = api_client.create_lane_rate(
        {"origin_location_id": loc_a["id"], "dest_location_id": loc_b["id"],
         "equipment_type": "TRUCK_10FT", "season": "OFF_PEAK",
         "base_rate_cents": 5000, "reposition_surcharge_cents": 0,
         "commission_rate": 0.10},
        make_customer_headers("some-customer-id"))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)


def test_dealer_agent_cannot_suspend_dealer():
    """PRD §2.1: "A well-formed request whose role is not authorized for the
    target endpoint is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "POST | /rental-network/dealers/{id}/suspend | Suspend dealer;
    mass-reassigns its live reservations | NetworkAdmin"

    Design: Corner/rbac/dealer_agent_cannot_suspend_dealer
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    resp = api_client.suspend_dealer(
        dealer["id"], make_dealer_agent_headers(dealer["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    after = validate_success(api_client.get_dealer(dealer["id"], TEST_USERS["admin"]))
    assert after["status"] == "ACTIVE"


def test_missing_auth_headers_rejected():
    """PRD §2.1: "A request missing either header, presenting an empty
    `X-User-ID`, or naming a role outside the declared set is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_rejected
    """
    resp = api_client.list_dealers(headers={"Content-Type": "application/json"})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_segregation_of_duties_claim_approve():
    """PRD §2.1: "First, the operator who approves or denies a `DamageClaim`
    must not be the operator whose identifier was recorded as that claim's
    `filer_user_id` at filing time. Second, the `FinanceReviewer` who pays a
    `DealerSettlement` must not be the operator who approved it. A violation of
    either pairing is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    Design: Corner/rbac/segregation_of_duties_claim_approve
    """
    scenario = setup_agreement()
    dealer_a = scenario["dealer_a"]
    agreement = scenario["agreement"]
    claim = validate_success(api_client.create_damage_claim(
        {"agreement_id": agreement["id"], "claimed_amount_cents": 10000},
        make_dealer_agent_headers(dealer_a["id"])), expected_status=201)
    # The filer cannot approve their own claim.
    resp = api_client.approve_damage_claim(
        claim["id"], {}, make_dealer_agent_headers(dealer_a["id"]))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    claim_after = validate_success(api_client.get_damage_claim(
        claim["id"], make_dealer_agent_headers(dealer_a["id"])))
    assert claim_after["status"] == "FILED"


def test_segregation_of_duties_settlement_pay():
    """PRD §3.11: "Payment requires `APPROVED` and, per §2.1, a payer whose
    `X-User-ID` differs from the approver's — the same person approving and
    paying is `ERR_SEGREGATION_OF_DUTIES`. Payment moves the settlement to
    `PAID`, terminal."

    Design: Corner/rbac/segregation_of_duties_settlement_pay
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    settlement = validate_success(api_client.create_dealer_settlement(
        {"dealer_id": dealer["id"], "period": "2026-Q4"},
        make_finance_headers("finance-1")), expected_status=201)
    validate_success(api_client.approve_dealer_settlement(
        settlement["id"], make_finance_headers("finance-1")))
    resp = api_client.pay_dealer_settlement(
        settlement["id"], make_finance_headers("finance-1"))
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, expected_status=403)
    paid = validate_success(api_client.pay_dealer_settlement(
        settlement["id"], make_finance_headers("finance-2")))
    assert paid["status"] == "PAID"


def test_customer_cannot_read_other_customers_reservation():
    """PRD §2.1: "When `X-User-Role` is `Customer`, `X-User-ID` is the `id` of
    the acting `Customer`; ownership checks on a `Reservation` compare the
    reservation's `customer_id` to `X-User-ID`."

    Design: Corner/rbac/customer_cannot_read_other_customers_reservation
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b)
    customer_1, _ = setup_customer(verify_dealer=dealer_a, verify=False,
                                   email_prefix="cr6a")
    customer_2, _ = setup_customer(verify_dealer=dealer_a, verify=False,
                                   email_prefix="cr6b")
    rsv = create_quoted_reservation(customer_1, dealer_a, loc_b)
    resp = api_client.get_reservation(
        rsv["id"], make_customer_headers(customer_2["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    own = validate_success(api_client.get_reservation(
        rsv["id"], make_customer_headers(customer_1["id"])))
    assert own["id"] == rsv["id"]


def test_existence_beats_business_referential_suspended_dealer():
    """PRD §2.8: "Every request is checked against a fixed ladder of
    validations, evaluated in the order given here; the first failing layer
    determines the error. (1) Authentication: `X-User-Role` present and one of
    the declared roles, then `X-User-ID` present and non-empty — failures are
    `ERR_UNAUTHENTICATED`. (2) Authorization: the role is permitted on the
    endpoint — `ERR_FORBIDDEN`. (3) Path existence: every identifier embedded
    in the URL is resolved left-to-right — a dangling path id yields
    `ERR_NOT_FOUND` (HTTP 404). (4) Body referential integrity: every foreign
    key in the request body — dealer, location, customer, reservation,
    agreement, vehicle profile, and so on — resolves to an existing row, else
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_suspended_dealer
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    validate_success(api_client.suspend_dealer(dealer["id"], TEST_USERS["admin"]))
    customer, _ = setup_customer(verify_dealer=dealer, verify=False)
    # The body FK (dest_location_id) dangles AND the origin dealer is
    # suspended; the existence layer (4) precedes dealer posture.
    resp = api_client.create_reservation(
        {
            "customer_id": customer["id"],
            "origin_dealer_id": dealer["id"],
            "dest_location_id": NON_EXISTENT_UUID,
            "equipment_type": "TRUCK_10FT",
            "rental_kind": "ONE_WAY",
            "pickup_date": "2026-11-10T10:00:00Z",
            "dropoff_date": "2026-11-12T10:00:00Z",
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)


def test_existence_beats_business_referential_dangling_customer_fk():
    """PRD §2.8: "Every request is checked against a fixed ladder of
    validations, evaluated in the order given here; the first failing layer
    determines the error. (1) Authentication: `X-User-Role` present and one of
    the declared roles, then `X-User-ID` present and non-empty — failures are
    `ERR_UNAUTHENTICATED`. (2) Authorization: the role is permitted on the
    endpoint — `ERR_FORBIDDEN`. (3) Path existence: every identifier embedded
    in the URL is resolved left-to-right — a dangling path id yields
    `ERR_NOT_FOUND` (HTTP 404). (4) Body referential integrity: every foreign
    key in the request body — dealer, location, customer, reservation,
    agreement, vehicle profile, and so on — resolves to an existing row, else
    `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

    Design: Difficulty/priority_pair_validation_conflict/existence_beats_business_referential_suspended_dealer
    """
    loc = setup_location()
    dealer = setup_dealer(loc)
    validate_success(api_client.suspend_dealer(dealer["id"], TEST_USERS["admin"]))
    # Same pairing, different dangling body FK (customer_id does not exist).
    resp = api_client.create_reservation(
        {
            "customer_id": NON_EXISTENT_UUID,
            "origin_dealer_id": dealer["id"],
            "dest_location_id": loc["id"],
            "equipment_type": "TRUCK_10FT",
            "rental_kind": "ONE_WAY",
            "pickup_date": "2026-11-10T10:00:00Z",
            "dropoff_date": "2026-11-12T10:00:00Z",
        },
        make_customer_headers(NON_EXISTENT_UUID),
    )
    validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND, expected_status=404)
