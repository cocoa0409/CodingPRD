"""Depth coverage of the computations the PRD reports two ways at once and of the
inclusive/exclusive edges of its numeric gates.

Three families of behaviour are pinned here. First the dual-variant computations:
the mileage waterfall run on planned mileage against the same waterfall run on
odometer mileage over the same three stops, and the order-to-door stopwatch
reported gross against the same stopwatch reported net of an accumulated zone
hold. Second the multi-step formulas whose composition order is part of the
contract: per-stop rounding before summation in the reimbursement waterfall, and
the drive-time tier surcharge before the food-subtotal waiver in the customer
delivery charge. Third the boundaries themselves: the inclusive drive-time
ceiling and its off-by-one-hundredth-of-a-mile neighbour, the at-least-one-stop
guard on route commitment, and the strictly-below cash gate on departure.
"""

import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers import fixtures as fx
from test_helpers import assertions as a
from test_helpers.constants import (
    CAR_COST_MODEL,
    DEFAULT_CLOCK,
    NOON_CLOCK,
    STORE_LAT_MICRO,
    STORE_LON_MICRO,
)
from test_helpers.test_users import (
    DISPATCHER_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

# The three planned mileages the shared ring produces for the A, A2 and NINE
# addresses, and the three odometer readings the driver books against them.
PLANNED_MILES_THREE_STOPS = [3.00, 3.00, 9.00]
ACTUAL_MILES_THREE_STOPS = [3.40, 2.80, 9.60]

THREE_STOP_ORDERS = [
    {"food_subtotal_cents": 2200, "payment_method": "CASH", "tip_cents": 500},
    {"food_subtotal_cents": 1900, "payment_method": "CARD", "tip_cents": 0},
    {"food_subtotal_cents": 2600, "payment_method": "CARD", "tip_cents": 300},
]


def _lines(dispatch_id, store_id):
    """Read a route's reimbursement ledger lines. The ledger is readable by the
    manager, the payee driver and a compliance officer."""
    return validate_paginated(
        api_client.list_reimbursement_lines(
            make_manager_headers(store_id), {"dispatch_id": dispatch_id, "limit": 100}
        )
    )


def _lines_by_sequence(lines, line_type):
    """Index one kind of ledger line by the stop sequence it snapshotted."""
    return {
        line["sequence_snapshot"]: line for line in lines if line["line_type"] == line_type
    }


def _returned_three_stop_route():
    """A three-stop route on planned mileage 3.00, 3.00 and 9.00, delivered
    against odometer readings of 3.40, 2.80 and 9.60 and checked back in."""
    return fx.setup_route(
        "RETURNED",
        ("A", "A2", "NINE"),
        planned_depart_at="2026-08-05T18:00:00Z",
        order_overrides=THREE_STOP_ORDERS,
        actual_miles=ACTUAL_MILES_THREE_STOPS,
    )


def test_settlement_prices_the_actual_variant_off_the_odometer_at_1203():
    """Settlement runs the waterfall over actual_miles, so the three stops price at
    361, 298 and 544 for 1203 cents against a frozen 1170-cent estimate.

    PRD: "To see the variance concretely: the three-stop route that estimated 1170 cents on planned mileage of 3.00, 3.00 and 9.00 miles settles against odometer readings of 3.40, 2.80 and 9.60 miles as 361 plus 298 plus 544, which is 1203, giving a `reimbursement_variance_cents` of positive 33."
    Design: Difficulty/dual_variant_calc/reimbursement_estimated_vs_actual_diverge_on_three_stop_route
    """
    world = _returned_three_stop_route()
    store_id = world["store"]["id"]
    dispatch_id = world["dispatch"]["id"]

    settled = validate_success(
        api_client.settle_dispatch(dispatch_id, make_manager_headers(store_id)), 200
    )

    assert settled["status"] == "SETTLED"
    assert settled["actual_reimbursement_cents"] == 1203
    assert settled["estimated_reimbursement_cents"] == 1170
    assert settled["reimbursement_variance_cents"] == 33
    a.assert_dispatch(settled)

    expected_actual = a.expected_stops_from_model(ACTUAL_MILES_THREE_STOPS, CAR_COST_MODEL)
    assert expected_actual == [361, 298, 544]

    lines, _meta = _lines(dispatch_id, store_id)
    by_sequence = _lines_by_sequence(lines, "ACTUAL_STOP")
    assert len(by_sequence) == 3, "one actual line per delivered stop"
    for sequence, amount in zip((1, 2, 3), (361, 298, 544)):
        line = by_sequence[sequence]
        assert line["amount_cents"] == amount
        assert line["basis"] == "ACTUAL"
        assert line["status"] == "ACCRUED"
        assert line["line_type"] == "ACTUAL_STOP"
        a.assert_reimbursement_line(line)


def test_settlement_leaves_the_estimated_variant_frozen_on_planned_mileage():
    """The estimated figure stays 1170 on planned mileage and every provisional line
    keeps its estimated amount, so the two bases differ at all three stops.

    PRD: "The **estimated** variant counts stops whose status is `PENDING`, `DELIVERED` or `REMADE` and uses each stop's `planned_miles`; it is what fills the route's `estimated_reimbursement_cents` at commitment time and what prices each provisional ledger line written at a door."
    Design: Difficulty/dual_variant_calc/reimbursement_estimated_vs_actual_diverge_on_three_stop_route
    """
    world = _returned_three_stop_route()
    store_id = world["store"]["id"]
    dispatch_id = world["dispatch"]["id"]

    settled = validate_success(
        api_client.settle_dispatch(dispatch_id, make_manager_headers(store_id)), 200
    )

    assert settled["estimated_reimbursement_cents"] == 1170, (
        "the estimated figure is frozen on planned mileage and is not re-run on odometer mileage"
    )
    assert settled["estimated_reimbursement_cents"] != 1203

    expected_estimated = a.expected_stops_from_model(PLANNED_MILES_THREE_STOPS, CAR_COST_MODEL)
    assert expected_estimated == [336, 315, 519]

    lines, _meta = _lines(dispatch_id, store_id)
    by_sequence = _lines_by_sequence(lines, "PROVISIONAL_STOP")
    assert len(by_sequence) == 3
    for sequence, amount in zip((1, 2, 3), (336, 315, 519)):
        line = by_sequence[sequence]
        assert line["amount_cents"] == amount
        assert line["basis"] == "ESTIMATED"
        assert line["status"] == "SUPERSEDED"

    actual_by_sequence = _lines_by_sequence(lines, "ACTUAL_STOP")
    for sequence, estimated_amount in zip((1, 2, 3), (336, 315, 519)):
        assert actual_by_sequence[sequence]["amount_cents"] != estimated_amount, (
            "the two bases consume the tier-1 cap at different stops, so no stop agrees"
        )


def test_settlement_accrues_only_the_actual_basis_onto_the_driver():
    """The driver's accrued figure re-derives to the 1203-cent actual total, the
    superseded provisional lines contributing nothing.

    PRD: "What a driver is actually owed on the next payroll run — the driver's `reimbursement_accrued_cents` — is the sum of `amount_cents` across every ledger line of that driver whose `status` is `ACCRUED`, and nothing else."
    Design: Difficulty/dual_variant_calc/reimbursement_estimated_vs_actual_diverge_on_three_stop_route
    """
    world = _returned_three_stop_route()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    dispatch_id = world["dispatch"]["id"]

    before = fx.read_driver(driver_id)
    assert before["reimbursement_accrued_cents"] == 0, (
        "every line written at a door is provisional and accrues nothing"
    )

    validate_success(
        api_client.settle_dispatch(dispatch_id, make_manager_headers(store_id)), 200
    )

    after = fx.read_driver(driver_id)
    assert after["reimbursement_accrued_cents"] == 1203
    assert after["reimbursement_accrued_cents"] != 1170
    a.assert_driver(after)


# The far-ridge destination: 170100 micro-degrees of latitude from the store is
# 11.34 grid miles, which models at 6 plus 35, one minute over the 40-minute
# ceiling, so the address classifies EDGE.
EDGE_LAT_MICRO = 39170100
EDGE_LON_MICRO = -84000000
HOLD_CLEARED_CLOCK = "2026-08-05T12:08:00Z"
DOOR_CLOCK = "2026-08-05T12:36:00Z"


def _edge_order_cleared_by_grant():
    """An order taken at noon on an EDGE address, parked, and cleared eight minutes
    later by a granted address dispute."""
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=())
    store_id = world["store"]["id"]
    address = fx.add_address_at(
        store_id, EDGE_LAT_MICRO, EDGE_LON_MICRO, line1="77 Far Ridge", crosses_barrier=False
    )
    assert address["grid_miles"] == 11.34
    assert address["drive_time_estimate_minutes"] == 41
    assert address["zone_state"] == "EDGE"

    fx.set_clock(NOON_CLOCK)
    order = fx.place_order(
        store_id,
        address["id"],
        food_subtotal_cents=2200,
        payment_method="CASH",
        tip_cents=500,
    )
    fx.decide_zone(order["id"], "HOLD")

    dispute = fx.open_dispute(address["id"])
    fx.review_dispute(dispute["id"], "START_REVIEW", store_id)
    fx.set_clock(HOLD_CLEARED_CLOCK)
    fx.review_dispute(
        dispute["id"], "GRANT", store_id, granted_until="2026-08-05T23:00:00Z"
    )

    world["address"] = address
    world["dispute"] = dispute
    world["order"] = fx.read_order(order["id"])
    return world


def _departed_edge_route():
    """The same order disclosed at 375, produced, committed and out of the door, with
    the clock standing at 12:36 ready for the handoff."""
    world = _edge_order_cleared_by_grant()
    order = world["order"]
    driver_id = world["driver"]["id"]

    fx.disclose_fee(order, 375, 500)
    fx.produce(order["id"], "START")
    fx.produce(order["id"], "READY")

    dispatch = fx.open_dispatch(driver_id, "2026-08-05T12:10:00Z")
    stop = fx.stack_stop(dispatch["id"], order["id"], 1)
    fx.lock_route(dispatch["id"])
    fx.depart_route(dispatch["id"], driver_id)
    fx.set_clock(DOOR_CLOCK)

    world["dispatch"] = dispatch
    world["stop"] = stop
    return world


def test_zone_hold_minutes_accrues_eight_whole_minutes_when_the_grant_clears_the_order():
    """The grant advances the parked order and accrues the eight whole minutes it
    spent between its noon hold and the 12:08 clearance.

    PRD: "Second, because the address now reads as in-zone, every order on that address whose fulfillment status is `ZONE_HELD` is automatically advanced `ZONE_HELD → ZONE_CLEARED`, processed in `created_at` ascending order across those orders; each such order accrues into its `zone_hold_minutes` the whole minutes it spent parked, computed as the difference between the logical clock and its `zone_held_at` in whole seconds, divided by 60 and truncated downward."
    Design: Difficulty/dual_variant_calc/order_to_door_gross_vs_net_after_eight_minute_zone_hold
    """
    world = _edge_order_cleared_by_grant()
    order = world["order"]

    assert order["fulfillment_status"] == "ZONE_CLEARED"
    assert order["zone_hold_minutes"] == 8
    assert order["order_to_door_gross_minutes"] is None
    assert order["order_to_door_net_minutes"] is None
    a.assert_order(order)


def test_order_to_door_gross_minutes_reads_thirty_six_from_placement_to_the_door():
    """The gross stopwatch spans noon to the 12:36 handoff and reports 36 whole
    minutes, ignoring the hold entirely.

    PRD: "`order_to_door_gross_minutes` is what the customer experienced: the difference between the order's `door_arrival_at` and its `placed_at`, taken in whole seconds, divided by 60 and truncated downward, so a partly elapsed minute is not yet counted."
    Design: Difficulty/dual_variant_calc/order_to_door_gross_vs_net_after_eight_minute_zone_hold
    """
    world = _departed_edge_route()
    driver_id = world["driver"]["id"]

    validate_success(
        api_client.door_arrival(
            world["dispatch"]["id"],
            world["stop"]["id"],
            {"actual_miles": 11.4, "cash_collected_cents": 3075},
            make_driver_headers(driver_id),
        ),
        200,
    )

    order = fx.read_order(world["order"]["id"])
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["order_to_door_gross_minutes"] == 36
    assert order["placed_at"] == "2026-08-05T12:00:00.000Z"
    assert order["door_arrival_at"] == "2026-08-05T12:36:00.000Z"
    a.assert_iso_millis(order["door_arrival_at"], "door_arrival_at")
    assert a.whole_minutes_between(order["placed_at"], order["door_arrival_at"]) == 36
    assert order["total_charge_cents"] == 3075


def test_order_to_door_net_minutes_reads_twenty_eight_after_the_eight_minute_hold():
    """The net stopwatch reads the same two instants but removes the eight held
    minutes, so it reports 28 rather than the gross 36.

    PRD: "`order_to_door_net_minutes` removes the delays the franchise is not judged on: it is the gross figure minus the order's accumulated `zone_hold_minutes` and minus its accumulated `remake_hold_minutes`, clamped so that it never falls below 0."
    Design: Difficulty/dual_variant_calc/order_to_door_gross_vs_net_after_eight_minute_zone_hold
    """
    world = _departed_edge_route()
    driver_id = world["driver"]["id"]

    validate_success(
        api_client.door_arrival(
            world["dispatch"]["id"],
            world["stop"]["id"],
            {"actual_miles": 11.4, "cash_collected_cents": 3075},
            make_driver_headers(driver_id),
        ),
        200,
    )

    order = fx.read_order(world["order"]["id"])
    assert order["order_to_door_net_minutes"] == 28
    assert order["order_to_door_net_minutes"] != order["order_to_door_gross_minutes"]
    assert order["zone_hold_minutes"] == 8
    assert (
        order["order_to_door_gross_minutes"] - order["order_to_door_net_minutes"]
        == order["zone_hold_minutes"]
    )
    a.assert_order_to_door(order)


# Two quarter-mile destinations, one due north of the store and one due west, so
# each stop's mileage term is 0.25 * 62 = 15.5 raw cents.
WEST_QUARTER_MILE_LAT_MICRO = 39000000
WEST_QUARTER_MILE_LON_MICRO = -84003750


def _two_quarter_mile_stops_stacked():
    """Two stops of exactly 0.25 planned miles each, stacked but not yet committed,
    on a route planned to leave at noon."""
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=("P",))
    store_id = world["store"]["id"]
    north = world["addresses"]["P"]
    west = fx.add_address_at(
        store_id,
        WEST_QUARTER_MILE_LAT_MICRO,
        WEST_QUARTER_MILE_LON_MICRO,
        line1="3 West Alley",
        crosses_barrier=False,
    )
    for address in (north, west):
        assert address["grid_miles"] == 0.25
        assert address["zone_state"] == "IN_ZONE"

    orders = [
        fx.add_ready_order(store_id, address["id"], payment_method="CARD")
        for address in (north, west)
    ]
    dispatch = fx.open_dispatch(world["driver"]["id"], NOON_CLOCK)
    stops = [fx.stack_stop(dispatch["id"], order["id"], 1) for order in orders]

    world["orders"] = orders
    world["dispatch"] = dispatch
    world["stops"] = stops
    return world


def test_commitment_rounds_each_quarter_mile_stop_before_summing_them_to_332():
    """Each 0.25-mile stop rounds 165.5 half up to 166 on its own, so the committed
    route estimates 332 cents.

    PRD: "The per-stop rounding is not cosmetic: two stops of 0.25 miles each price at 150 plus 15.5, which is 165.5, rounding half up to 166 per stop for a route total of 332 — summing the raw subtotals first would have given 331."
    Design: Difficulty/combinatorial_formula/per_stop_rounding_before_summation_yields_332_not_331
    """
    world = _two_quarter_mile_stops_stacked()

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert locked["status"] == "LOCKED"
    assert locked["estimated_reimbursement_cents"] == 332
    assert a.expected_stops_from_model([0.25, 0.25], CAR_COST_MODEL) == [166, 166]
    assert a.round_half_up(165.5) == 166
    a.assert_dispatch(locked)

    for stop in fx.list_route_stops(world["dispatch"]["id"]):
        assert stop["planned_miles"] == 0.25
        a.assert_two_decimal_miles(stop["planned_miles"], "planned_miles")


def test_commitment_does_not_sum_raw_mileage_first_or_truncate_the_half_cent():
    """Summing the raw subtotals before rounding would estimate 331 and truncating
    each stop would estimate 330; the committed figure is neither.

    PRD: "**Round that subtotal half up to a whole number of cents, then raise it to `min_reimbursement_per_stop_cents` if it falls below that floor, and only then add it to the running total** — the rounding happens once per stop, the floor is applied after the rounding, and the summation happens after both."
    Design: Difficulty/combinatorial_formula/per_stop_rounding_before_summation_yields_332_not_331
    """
    world = _two_quarter_mile_stops_stacked()

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    estimated = locked["estimated_reimbursement_cents"]
    assert estimated != 331, "the two raw subtotals were summed before the rounding"
    assert estimated != 330, "the half cent was truncated instead of rounded half up"
    assert estimated == 332
    assert estimated == 2 * 166
    # The per-stop floor of 100 cents is below the rounded subtotal, so it never binds
    # here and cannot be what produced the figure.
    assert 166 > CAR_COST_MODEL["min_reimbursement_per_stop_cents"]


def test_commitment_models_the_two_quarter_mile_stops_as_a_fifteen_minute_round_trip():
    """Two one-minute outbound legs, twelve minutes of handoff and a one-minute home
    leg make 15 minutes, putting the expected return at 12:15.

    PRD: "`route_minutes` is the sum of those three components, and `expected_return_at` is `planned_depart_at` advanced by that many minutes."
    Design: Difficulty/combinatorial_formula/per_stop_rounding_before_summation_yields_332_not_331
    """
    world = _two_quarter_mile_stops_stacked()

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert locked["route_minutes"] == 15
    assert a.expected_route_minutes([0.25, 0.25], 3, 6) == 15
    assert locked["expected_return_at"] == "2026-08-05T12:15:00.000Z"
    a.assert_iso_millis(locked["expected_return_at"], "expected_return_at")
    # instant_plus renders the shorter ...Z input form, so compare parsed instants:
    # PRD 2.4 requires every response datetime to carry three fractional digits.
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(locked["planned_depart_at"], minutes=15)
    )
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]


def test_commitment_writes_no_reimbursement_ledger_line_before_any_door():
    """Commitment prices the route but writes nothing to the ledger; provisional
    lines appear only when a door is knocked on.

    PRD: "Alongside the cascade, one provisional reimbursement ledger line is written for this stop: its `line_type` is `PROVISIONAL_STOP`, its `basis` is `ESTIMATED`, its `status` is `PROVISIONAL`, its `sequence_snapshot` records the stop's `sequence`, and its `amount_cents` is this stop's stop-total under the estimated variant of the mileage waterfall."
    Design: Difficulty/combinatorial_formula/per_stop_rounding_before_summation_yields_332_not_331
    """
    world = _two_quarter_mile_stops_stacked()
    store_id = world["store"]["id"]
    dispatch_id = world["dispatch"]["id"]

    locked = validate_success(api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)
    assert locked["estimated_reimbursement_cents"] == 332

    lines, meta = _lines(dispatch_id, store_id)
    assert lines == []
    assert meta["total_count"] == 0


def _mid_tier_world():
    """A store on the standard 399-cent base fee with one 6.33-mile destination that
    models at 25 drive-time minutes, which is the top of the MID tier."""
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK,
        address_keys=("D",),
        with_cost_model=False,
        with_driver=False,
    )
    assert world["store"]["delivery_fee_cents"] == 399
    return world


def _mid_tier_order_payload(world):
    """A 2000-cent card ticket with no tip on that destination."""
    return {
        "store_id": world["store"]["id"],
        "service_address_id": world["addresses"]["D"]["id"],
        "customer_name": "Dee",
        "customer_phone": "+15135550104",
        "food_subtotal_cents": 2000,
        "payment_method": "CARD",
        "tip_cents": 0,
    }


def test_mid_tier_order_charges_275_after_the_waiver_halves_the_surcharged_base():
    """The surcharge lands first (399 plus 150 is 549) and the half waiver then takes
    274.5, which rounds half up to a charged fee of 275 and a total of 2275.

    PRD: "A 25-minute address with 3000 cents of food and a 700-cent tip lands in `MID` with a base of 549, a waiver of 100, a charged fee of 0 and a total of 3700; the same 25-minute address with exactly 2000 cents of food and no tip lands on a waiver of 50 and a fee of 275 (274.5 rounded half up), for a total of 2275."
    Design: Difficulty/combinatorial_formula/delivery_charge_tier_then_waiver_ordering_yields_275
    """
    world = _mid_tier_world()

    order = validate_success(
        api_client.create_order(_mid_tier_order_payload(world), DISPATCHER_HEADERS), 201
    )

    assert order["fee_tier"] == "MID"
    assert order["base_delivery_fee_cents"] == 549
    assert order["fee_waiver_pct"] == 50
    assert order["delivery_fee_cents"] == 275
    assert order["total_charge_cents"] == 2275
    assert order["fulfillment_status"] == "PLACED"
    assert order["settlement_status"] == "UNDISCLOSED"
    assert a.expected_order_pricing(25, 399, 2000, 0) == {
        "fee_tier": "MID",
        "base_delivery_fee_cents": 549,
        "fee_waiver_pct": 50,
        "delivery_fee_cents": 275,
        "total_charge_cents": 2275,
    }
    a.assert_order(order)


def test_mid_tier_order_does_not_waive_the_store_fee_alone_or_omit_the_waiver():
    """Halving the store's 399 alone would charge 200, halving before the surcharge
    would charge 350 and leaving the waiver off would charge 549.

    PRD: "The fourth step computes the `delivery_fee_cents` actually charged by multiplying `base_delivery_fee_cents` by the complement of the waiver percentage — that is, by 100 minus `fee_waiver_pct` — dividing by 100, and rounding the result half up to a whole cent."
    Design: Difficulty/combinatorial_formula/delivery_charge_tier_then_waiver_ordering_yields_275
    """
    world = _mid_tier_world()

    order = validate_success(
        api_client.create_order(_mid_tier_order_payload(world), DISPATCHER_HEADERS), 201
    )

    fee = order["delivery_fee_cents"]
    assert fee != 200, "the waiver was applied to the store base fee without the surcharge"
    assert fee != 350, "the waiver was applied before the tier surcharge was added"
    assert fee != 549, "the waiver was not applied to the charged fee at all"
    assert fee == 275
    assert fee == a.round_half_up(549 * (100 - 50) / 100)
    a.assert_cents(fee, "delivery_fee_cents")
    assert order["total_charge_cents"] == 2000 + 275 + 0


def test_the_6_33_mile_destination_models_at_25_minutes_which_selects_the_mid_tier():
    """The 6.33-mile destination models at 6 plus 19 minutes, and 25 minutes is what
    puts the ticket in MID rather than BASE or FAR.

    PRD: "A 6.33-mile address models at 6 plus 19, which is 25; a 6.34-mile address models at 6 plus 20, which is 26."
    Design: Difficulty/combinatorial_formula/delivery_charge_tier_then_waiver_ordering_yields_275
    """
    world = _mid_tier_world()
    address = fx.read_address(world["addresses"]["D"]["id"])

    assert address["grid_miles"] == 6.33
    assert address["drive_time_estimate_minutes"] == 25
    assert address["zone_state"] == "IN_ZONE"
    assert a.expected_drive_minutes(6.33, 6, 3) == 25
    assert a.expected_fee_tier(25) == "MID"
    a.assert_service_address(address)

    order = validate_success(
        api_client.create_order(_mid_tier_order_payload(world), DISPATCHER_HEADERS), 201
    )
    assert order["fee_tier"] == "MID"
    assert order["base_delivery_fee_cents"] == 549


# Three destinations due north of the store, 150 micro-degrees (0.01 mile) apart at
# the tight end: 11.00 miles models at 39 minutes, 11.33 at 40 and 11.34 at 41
# against a 40-minute ceiling.
UNDER_CEILING_LAT_MICRO = 39165000
AT_CEILING_LAT_MICRO = 39169950
OVER_CEILING_LAT_MICRO = 39170100


def _drive_time_boundary_world():
    """A store with the 40-minute ceiling in force and the two neighbours of the
    boundary already filed."""
    world = fx.setup_operational_store(
        clock=DEFAULT_CLOCK,
        address_keys=(),
        with_cost_model=False,
        with_driver=False,
    )
    store_id = world["store"]["id"]
    world["under"] = fx.add_address_at(
        store_id, UNDER_CEILING_LAT_MICRO, STORE_LON_MICRO, line1="60 Under Ridge"
    )
    world["over"] = fx.add_address_at(
        store_id, OVER_CEILING_LAT_MICRO, STORE_LON_MICRO, line1="77 Far Ridge"
    )
    return world


def _at_ceiling_payload(world):
    """The destination that models at exactly the ceiling."""
    return {
        "store_id": world["store"]["id"],
        "line1": "70 Ceiling Ridge",
        "latitude_micro": AT_CEILING_LAT_MICRO,
        "longitude_micro": STORE_LON_MICRO,
        "crosses_barrier": False,
    }


def test_an_address_modelling_at_exactly_forty_minutes_classifies_in_zone():
    """11.33 grid miles models at 6 plus 34, which is exactly the 40-minute ceiling,
    and the inclusive ceiling accepts it as IN_ZONE.

    PRD: "A point inside the ring whose `drive_time_estimate_minutes` is **at or below** the in-force `max_drive_time_minutes` is `IN_ZONE` — the ceiling is inclusive, so a 25-minute estimate against a 25-minute ceiling is accepted."
    Design: Difficulty/boundary_precision_check/drive_time_ceiling_is_inclusive_at_forty_and_edge_at_forty_one
    """
    world = _drive_time_boundary_world()

    address = validate_success(
        api_client.create_service_address(_at_ceiling_payload(world), DISPATCHER_HEADERS), 201
    )

    assert address["grid_miles"] == 11.33
    assert address["drive_time_estimate_minutes"] == 40
    assert address["zone_state"] == "IN_ZONE"
    assert address["effective_zone_state"] == "IN_ZONE"
    assert address["override_state"] is None
    assert address["override_until"] is None
    assert address["evaluated_zone_version_number"] == 1
    assert a.expected_grid_miles(
        AT_CEILING_LAT_MICRO, STORE_LON_MICRO, STORE_LAT_MICRO, STORE_LON_MICRO
    ) == 11.33
    a.assert_service_address(address)


def test_the_neighbour_one_hundredth_of_a_mile_further_out_classifies_edge_at_forty_one():
    """11.34 grid miles models at 6 plus 35, which is 41 and one minute past the
    ceiling, so the neighbouring address is EDGE rather than IN_ZONE.

    PRD: "A point inside the ring whose estimate exceeds the ceiling is `EDGE`: too far to promise, but close enough to argue about, and therefore eligible for the dispute process, for a delivery hold, and for a carryout redirect."
    Design: Difficulty/boundary_precision_check/drive_time_ceiling_is_inclusive_at_forty_and_edge_at_forty_one
    """
    world = _drive_time_boundary_world()

    at_ceiling = validate_success(
        api_client.create_service_address(_at_ceiling_payload(world), DISPATCHER_HEADERS), 201
    )
    over = fx.read_address(world["over"]["id"])

    assert over["grid_miles"] == 11.34
    assert over["drive_time_estimate_minutes"] == 41
    assert over["zone_state"] == "EDGE"
    assert over["effective_zone_state"] == "EDGE"
    assert over["evaluated_zone_version_number"] == 1
    assert over["latitude_micro"] - at_ceiling["latitude_micro"] == 150
    assert over["drive_time_estimate_minutes"] - at_ceiling["drive_time_estimate_minutes"] == 1
    assert over["zone_state"] != at_ceiling["zone_state"]
    a.assert_service_address(over)


def test_the_mileage_term_is_taken_to_the_next_whole_minute_not_rounded():
    """11.00 miles gives an exact 33-minute term for 39 minutes, while 11.33 miles
    gives 33.99 taken up to 34 rather than rounded to 34 by accident.

    PRD: "The second is the mileage term: `grid_miles` multiplied by `minutes_per_mile`, then rounded **up** to the next whole minute — the rounding-up applies to this term alone and never to the total."
    Design: Difficulty/boundary_precision_check/drive_time_ceiling_is_inclusive_at_forty_and_edge_at_forty_one
    """
    world = _drive_time_boundary_world()

    at_ceiling = validate_success(
        api_client.create_service_address(_at_ceiling_payload(world), DISPATCHER_HEADERS), 201
    )
    under = fx.read_address(world["under"]["id"])

    assert under["grid_miles"] == 11.00
    assert under["drive_time_estimate_minutes"] == 39
    assert under["zone_state"] == "IN_ZONE"
    assert a.expected_drive_minutes(11.00, 6, 3) == 39
    assert a.expected_drive_minutes(11.33, 6, 3) == 40
    assert a.expected_drive_minutes(11.34, 6, 3) == 41
    assert at_ceiling["drive_time_estimate_minutes"] - under["drive_time_estimate_minutes"] == 1
    assert under["evaluated_zone_version_number"] == 1
    assert under["effective_zone_state"] == under["zone_state"]


def test_an_order_on_the_forty_minute_address_can_be_cleared_for_delivery():
    """Because the boundary address reads IN_ZONE, the clearance accepts its order.

    PRD: "`CLEAR` accepts the order for delivery, advancing it `PLACED → ZONE_CLEARED` or, for an order already parked, `ZONE_HELD → ZONE_CLEARED`."
    Design: Difficulty/boundary_precision_check/drive_time_ceiling_is_inclusive_at_forty_and_edge_at_forty_one
    """
    world = _drive_time_boundary_world()
    at_ceiling = validate_success(
        api_client.create_service_address(_at_ceiling_payload(world), DISPATCHER_HEADERS), 201
    )
    order = fx.place_order(world["store"]["id"], at_ceiling["id"])

    cleared = validate_success(
        api_client.zone_decision(order["id"], {"action": "CLEAR"}, DISPATCHER_HEADERS), 200
    )

    assert cleared["fulfillment_status"] == "ZONE_CLEARED"
    assert cleared["fee_tier"] == "FAR"
    assert cleared["settlement_status"] == "UNDISCLOSED"
    a.assert_order(cleared)


def test_an_order_on_the_forty_one_minute_neighbour_is_refused_as_out_of_area():
    """The neighbouring EDGE address is one minute too far to promise, so clearing its
    order is refused as out of area.

    PRD: "And the destination's `effective_zone_state` must read `IN_ZONE`, or the request fails with `ERR_ADDRESS_OUT_OF_AREA` — which for a parked edge address means the clearance can only succeed while a granted dispute's `override_until` is still strictly ahead of the clock."
    Design: Difficulty/boundary_precision_check/drive_time_ceiling_is_inclusive_at_forty_and_edge_at_forty_one
    """
    world = _drive_time_boundary_world()
    order = fx.place_order(world["store"]["id"], world["over"]["id"])
    assert order["fulfillment_status"] == "PLACED"

    validate_error(
        api_client.zone_decision(order["id"], {"action": "CLEAR"}, DISPATCHER_HEADERS),
        ApiErrorId.ERR_ADDRESS_OUT_OF_AREA.value,
    )

    unchanged = fx.read_order(order["id"])
    assert unchanged["fulfillment_status"] == "PLACED"
    assert unchanged["version"] == order["version"]


EVENING_DEPART_AT = "2026-08-05T18:00:00Z"


def _empty_draft_route():
    """One ready 3.00-mile order and an empty draft route for a qualified driver, the
    order deliberately left unstacked so the route carries no counted stop."""
    world = fx.setup_operational_store(clock=DEFAULT_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], EVENING_DEPART_AT)

    assert dispatch["status"] == "DRAFT"
    assert dispatch["stop_count"] == 0
    world["order"] = order
    world["dispatch"] = dispatch
    return world


def test_committing_a_route_with_no_stops_is_refused_and_writes_nothing():
    """A route standing at a stop count of 0 cannot be committed, and the refusal
    leaves every field the commitment would have written null.

    PRD: "And the route must carry at least one counted stop, or the commitment is refused with `ERR_DISPATCH_HAS_NO_STOPS` — an empty route has no schedule to resolve, no last stop to drive home from, and nothing to reimburse."
    Design: Difficulty/boundary_precision_check/lock_requires_at_least_one_stop_at_the_zero_to_one_boundary
    """
    world = _empty_draft_route()

    validate_error(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS),
        ApiErrorId.ERR_DISPATCH_HAS_NO_STOPS.value,
    )

    unchanged = fx.read_dispatch(world["dispatch"]["id"])
    assert unchanged["status"] == "DRAFT"
    assert unchanged["stop_count"] == 0
    assert unchanged["committed_hot_bag_slots"] == 0
    assert unchanged["route_minutes"] is None
    assert unchanged["expected_return_at"] is None
    assert unchanged["resolved_cost_model_id"] is None
    assert unchanged["estimated_reimbursement_cents"] is None
    assert unchanged["version"] == world["dispatch"]["version"]
    assert fx.read_order(world["order"]["id"])["fulfillment_status"] == "READY"


def test_the_same_route_commits_once_a_single_stop_takes_the_count_to_one():
    """One stop is the whole difference: the identical commitment then succeeds and
    writes the route model, the schedule and the estimate together.

    PRD: "Committing a route therefore writes four fields at once: `route_minutes` and `expected_return_at` from the round-trip model, `resolved_cost_model_id` from the selector, and `estimated_reimbursement_cents` from the estimated variant of the waterfall."
    Design: Difficulty/boundary_precision_check/lock_requires_at_least_one_stop_at_the_zero_to_one_boundary
    """
    world = _empty_draft_route()
    dispatch_id = world["dispatch"]["id"]

    stacked = fx.stack_stop(dispatch_id, world["order"]["id"], 1)
    assert stacked["planned_miles"] == 3.00
    assert fx.read_dispatch(dispatch_id)["stop_count"] == 1

    locked = validate_success(api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS), 200)

    assert locked["status"] == "LOCKED"
    assert locked["route_minutes"] == 24
    assert a.expected_route_minutes([3.00], 3, 6) == 24
    assert locked["expected_return_at"] == "2026-08-05T18:24:00.000Z"
    assert locked["resolved_cost_model_id"] == world["cost_model"]["id"]
    assert locked["estimated_reimbursement_cents"] == 336
    assert locked["committed_hot_bag_slots"] == 1
    a.assert_dispatch(locked)


def test_removing_the_only_stop_returns_the_route_to_draft_and_blocks_it_again():
    """Un-stacking the single stop drops the count back to 0 and sends the route back
    to DRAFT, where the commitment is refused exactly as before.

    PRD: "When the removal drops `stop_count` to 0 the route returns `STACKED → DRAFT`."
    Design: Difficulty/boundary_precision_check/lock_requires_at_least_one_stop_at_the_zero_to_one_boundary
    """
    world = _empty_draft_route()
    dispatch_id = world["dispatch"]["id"]

    stop = fx.stack_stop(dispatch_id, world["order"]["id"], 1)
    assert fx.read_dispatch(dispatch_id)["status"] == "STACKED"

    released = validate_success(
        api_client.delete_dispatch_stop(dispatch_id, stop["id"], DISPATCHER_HEADERS), 200
    )
    assert released["status"] == "DRAFT"
    assert released["stop_count"] == 0
    assert released["committed_hot_bag_slots"] == 0

    validate_error(
        api_client.lock_dispatch(dispatch_id, DISPATCHER_HEADERS),
        ApiErrorId.ERR_DISPATCH_HAS_NO_STOPS.value,
    )
    assert fx.read_dispatch(dispatch_id)["status"] == "DRAFT"


CASH_LIMIT_CENTS = 2900
SECOND_DEPART_AT = "2026-08-05T14:00:00Z"


def _driver_holding_exactly_the_cash_limit():
    """A driver who has taken a single 2900-cent cash ticket back to a store whose
    cash ceiling is exactly 2900, with a second committed route waiting at 14:00."""
    world = fx.setup_route(
        "RETURNED",
        ("A",),
        planned_depart_at="2026-08-05T12:05:00Z",
        order_overrides={"payment_method": "CASH"},
        actual_miles=[3.0],
        clock=NOON_CLOCK,
        store_overrides={"cash_limit_cents": CASH_LIMIT_CENTS},
    )
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]
    assert world["orders"][0]["total_charge_cents"] == 2900

    second_address = fx.add_address(store_id, "A2")
    second_order = fx.add_ready_order(store_id, second_address["id"], payment_method="CARD")
    second_dispatch = fx.open_dispatch(driver_id, SECOND_DEPART_AT)
    fx.stack_stop(second_dispatch["id"], second_order["id"], 1)
    world["second_dispatch"] = fx.lock_route(second_dispatch["id"])
    world["second_order"] = second_order
    return world


def test_departing_with_cash_exactly_at_the_limit_is_refused_with_payment_required():
    """Holding 2900 against a 2900-cent ceiling is not below the limit, so the second
    route cannot leave and stays committed.

    PRD: "A driver holding exactly the limit is already blocked and must visit the safe first; the refusal is `ERR_CASH_LIMIT_REACHED` and it carries HTTP 402."
    Design: Difficulty/boundary_precision_check/cash_limit_blocks_depart_at_exactly_the_limit_but_not_one_cent_below
    """
    world = _driver_holding_exactly_the_cash_limit()
    driver_id = world["driver"]["id"]
    dispatch_id = world["second_dispatch"]["id"]

    driver = fx.read_driver(driver_id)
    assert driver["cash_on_hand_cents"] == CASH_LIMIT_CENTS
    assert fx.read_store(world["store"]["id"])["cash_limit_cents"] == CASH_LIMIT_CENTS
    assert driver["cash_posture"] == "DROP_REQUIRED"

    validate_error(
        api_client.depart_dispatch(dispatch_id, make_driver_headers(driver_id)),
        ApiErrorId.ERR_CASH_LIMIT_REACHED.value,
    )

    unchanged = fx.read_dispatch(dispatch_id)
    assert unchanged["status"] == "LOCKED"
    assert unchanged["departed_at"] is None
    assert unchanged["version"] == world["second_dispatch"]["version"]
    assert fx.read_driver(driver_id)["cash_on_hand_cents"] == CASH_LIMIT_CENTS


def test_a_one_cent_safe_drop_takes_the_driver_below_the_limit_and_unblocks_departure():
    """Dropping a single cent leaves 2899, which is strictly below the ceiling, so the
    posture clears and the identical departure succeeds.

    PRD: "It lowers the driver's `cash_on_hand_cents` and raises the store's `safe_deposit_total_cents` by `amount_cents`, re-derives the driver's `cash_posture` — which is how a `DROP_REQUIRED` driver becomes `CLEAR` again and is unblocked to depart — and increments both the driver's `version` and the store's `version` by 1 each."
    Design: Difficulty/boundary_precision_check/cash_limit_blocks_depart_at_exactly_the_limit_but_not_one_cent_below
    """
    world = _driver_holding_exactly_the_cash_limit()
    driver_id = world["driver"]["id"]
    dispatch_id = world["second_dispatch"]["id"]

    fx.record_safe_drop(driver_id, 1)
    driver = fx.read_driver(driver_id)
    assert driver["cash_on_hand_cents"] == 2899
    assert driver["cash_posture"] == "CLEAR"

    departed = validate_success(
        api_client.depart_dispatch(dispatch_id, make_driver_headers(driver_id)), 200
    )

    assert departed["status"] == "EN_ROUTE"
    assert departed["departed_at"] is not None
    a.assert_iso_millis(departed["departed_at"], "departed_at")
    assert fx.read_order(world["second_order"]["id"])["fulfillment_status"] == "EN_ROUTE"


def test_the_one_cent_drop_moves_cash_into_the_safe_without_changing_what_was_collected():
    """The drop raises the store's safe total to 1 while the collected total stays at
    the 2900 the driver took at the door.

    PRD: "At store level, `cash_collected_total_cents` is the sum of the collected component across the store's drivers and `safe_deposit_total_cents` is the sum of the recorded-drop component across the same drivers."
    Design: Difficulty/boundary_precision_check/cash_limit_blocks_depart_at_exactly_the_limit_but_not_one_cent_below
    """
    world = _driver_holding_exactly_the_cash_limit()
    store_id = world["store"]["id"]
    driver_id = world["driver"]["id"]

    before = fx.read_store(store_id)
    assert before["cash_collected_total_cents"] == 2900
    assert before["safe_deposit_total_cents"] == 0

    drop = fx.record_safe_drop(driver_id, 1)
    assert drop["amount_cents"] == 1
    assert drop["status"] == "RECORDED"

    after = fx.read_store(store_id)
    assert after["safe_deposit_total_cents"] == 1
    assert after["cash_collected_total_cents"] == 2900
    a.assert_store(after)
    a.assert_cash_conservation(fx.read_cash_reconciliation(store_id))
