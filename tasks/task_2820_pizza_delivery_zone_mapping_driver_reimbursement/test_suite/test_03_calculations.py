"""Arithmetic compliance for the Store Operations API: grid mileage from the two
axis deltas, the three-term drive-time estimate with its single surcharge, the
integer ray-casting zone verdict, the five-step customer delivery charge, the
round-trip route-duration model, the cumulative-tier mileage waterfall with its
per-stop rounding and per-stop floor, the order-to-door stopwatch and the
complaint remedy formulas — each pinned to its published literal and to the
rounding discipline (integer cents, two-decimal mileage, half up, ceil per leg,
truncate on elapsed minutes) that the specification fixes."""

import pytest

from prd_bench_local_runner.testing import validate_success, validate_paginated

from test_helpers import api_client
from test_helpers import fixtures as fx
from test_helpers import factories as f
from test_helpers import assertions as a
from test_helpers.constants import (
    ADDRESS_DRIVE_MINUTES,
    ADDRESS_GRID_MILES,
    DEFAULT_CLOCK,
    FEE_TIER_SURCHARGE_CENTS,
    MICRO_PER_MILE,
    NOON_CLOCK,
    PEAK_CLOCK,
    STORE_LAT_MICRO,
    STORE_LON_MICRO,
    TEST_ZONE_MODEL,
    WAIVER_FULL_THRESHOLD_CENTS,
    WAIVER_HALF_THRESHOLD_CENTS,
)
from test_helpers.test_users import (
    CARE_HEADERS,
    DISPATCHER_HEADERS,
    make_driver_headers,
    make_manager_headers,
)

DEPART_AT = "2026-08-05T12:05:00Z"


def test_grid_miles_add_both_axis_deltas_rather_than_the_hypotenuse():
    """An address north and west of the store measures the sum of the two deltas,
    and the drive-time estimate inherits that rectilinear figure.

    PRD: "Pizza mileage is reimbursed on street distance, and the store models its streets as an axis-aligned grid, so the two coordinate deltas are added rather than combined as the hypotenuse of a triangle."
    Design: Corner/calculations/grid_distance_adds_both_axis_deltas_instead_of_euclidean
    """
    store, zone_version = fx.bootstrap(clock=DEFAULT_CLOCK)
    payload = f.create_service_address_payload(
        store["id"], 39090000, -84045000, line1="90 Grid Ave", crosses_barrier=False
    )

    address = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )

    a.assert_service_address(address)
    a.assert_two_decimal_miles(address["grid_miles"], "grid_miles")
    assert address["grid_miles"] == 9.00, "(90000 + 45000) / 15000 grid miles"
    assert address["grid_miles"] == a.expected_grid_miles(
        39090000, -84045000, STORE_LAT_MICRO, STORE_LON_MICRO
    )
    assert address["grid_miles"] == (90000 + 45000) / MICRO_PER_MILE
    assert address["grid_miles"] != 6.71, "the hypotenuse is never the answer"
    assert address["drive_time_estimate_minutes"] == 33, "6 + ceil(9.00 * 3) + 0"
    assert address["drive_time_estimate_minutes"] == a.expected_drive_minutes(
        9.00,
        TEST_ZONE_MODEL["base_drive_minutes"],
        TEST_ZONE_MODEL["minutes_per_mile"],
    )
    assert address["zone_state"] == "IN_ZONE", "33 is at or below the 40-minute ceiling"
    assert address["effective_zone_state"] == "IN_ZONE"
    assert address["override_state"] is None and address["override_until"] is None
    assert address["evaluated_zone_version_number"] == zone_version["version_number"]


def test_grid_miles_round_half_up_to_two_decimals_and_the_mileage_term_ceils_after():
    """A raw 6.665 miles is recorded as 6.67, and because the mileage term is a
    ceiling that extra hundredth of a mile shows up in the drive time.

    PRD: "The quotient, rounded half up to two decimal places, is the address's `grid_miles`."
    Design: Corner/calculations/grid_distance_rounds_half_up_and_the_ceil_term_inherits_the_extra_cent_of_a_mile
    """
    store, _zone_version = fx.bootstrap(clock=DEFAULT_CLOCK)
    payload = f.create_service_address_payload(
        store["id"], 39066650, -84033325, line1="665 Halfway Ln", crosses_barrier=False
    )

    address = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )

    a.assert_two_decimal_miles(address["grid_miles"], "grid_miles")
    assert (66650 + 33325) / MICRO_PER_MILE == 6.665, "the raw quotient sits on a half"
    assert address["grid_miles"] == 6.67, "half up, never down to 6.66"
    assert address["grid_miles"] == a.round_half_up_2dp(
        (66650 + 33325) / MICRO_PER_MILE
    )
    assert address["drive_time_estimate_minutes"] == 27, "6 + ceil(6.67 * 3)"
    assert address["drive_time_estimate_minutes"] == a.expected_drive_minutes(
        6.67,
        TEST_ZONE_MODEL["base_drive_minutes"],
        TEST_ZONE_MODEL["minutes_per_mile"],
    )
    assert (
        a.expected_drive_minutes(
            6.66,
            TEST_ZONE_MODEL["base_drive_minutes"],
            TEST_ZONE_MODEL["minutes_per_mile"],
        )
        == 26
    ), "a truncated 6.66 would have modelled one minute less"
    assert address["drive_time_estimate_minutes"] != 26
    assert address["zone_state"] == "IN_ZONE", "27 is at or below the 40-minute ceiling"


def test_drive_time_charges_only_the_greater_of_the_peak_and_barrier_surcharges():
    """An address that both crosses a barrier and is classified during the dinner
    rush pays the larger of the two surcharges once, not both added together.

    PRD: "The third is a single surcharge, and this is the step most easily got wrong: the peak-hour component is `peak_surcharge_minutes` when the UTC hour of the logical clock is 17, 18, 19 or 20, and zero otherwise; the barrier component is `barrier_surcharge_minutes` when the address's `crosses_barrier` flag is true, and zero otherwise; the surcharge actually applied is the **greater of the two components**, not their sum, because a driver crossing a river during the dinner rush is delayed once rather than twice."
    Design: Corner/calculations/drive_time_surcharge_is_the_max_of_peak_and_barrier_not_their_sum
    """
    store, _zone_version = fx.bootstrap(clock=PEAK_CLOCK)
    payload = f.create_service_address_payload(
        store["id"], 39030000, -84015000, line1="12 Bridge St", crosses_barrier=True
    )

    address = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )

    assert address["crosses_barrier"] is True
    assert address["grid_miles"] == 3.00, "(30000 + 15000) / 15000 grid miles"
    assert address["drive_time_estimate_minutes"] == 22, "6 + ceil(9.0) + max(7, 4)"
    assert address["drive_time_estimate_minutes"] == a.expected_drive_minutes(
        3.00,
        TEST_ZONE_MODEL["base_drive_minutes"],
        TEST_ZONE_MODEL["minutes_per_mile"],
        peak=True,
        crosses_barrier=True,
        peak_surcharge_minutes=TEST_ZONE_MODEL["peak_surcharge_minutes"],
        barrier_surcharge_minutes=TEST_ZONE_MODEL["barrier_surcharge_minutes"],
    )
    assert address["drive_time_estimate_minutes"] != 26, "7 + 4 is never charged"
    assert address["drive_time_estimate_minutes"] != 15, "the surcharge still applies"
    assert address["zone_state"] == "IN_ZONE"


def test_fee_tier_reads_the_surcharged_drive_time_estimate_as_mid():
    """The surcharged 22-minute estimate lands the order in the middle fee tier,
    because the tier is picked from the estimate the address carries.

    PRD: "The first step reads the destination address's `drive_time_estimate_minutes` and picks the `fee_tier`: an estimate of 15 minutes or less is `BASE`; an estimate above 15 but at most 25 minutes is `MID`; anything above 25 minutes is `FAR`."
    Design: Corner/calculations/drive_time_surcharge_is_the_max_of_peak_and_barrier_not_their_sum
    """
    store, _zone_version = fx.bootstrap(clock=PEAK_CLOCK)
    address = fx.add_address_at(
        store["id"], 39030000, -84015000, line1="12 Bridge St", crosses_barrier=True
    )
    assert address["drive_time_estimate_minutes"] == 22
    payload = f.create_order_payload(store["id"], address["id"])

    order = validate_success(api_client.create_order(payload, DISPATCHER_HEADERS), 201)

    a.assert_order(order)
    assert order["fee_tier"] == "MID", "22 minutes is above 15 and at most 25"
    assert order["fee_tier"] == a.expected_fee_tier(22)
    assert order["fee_tier"] != "BASE" and order["fee_tier"] != "FAR"
    expected = a.expected_order_pricing(22, 399, 2200, 500)
    assert order["base_delivery_fee_cents"] == expected["base_delivery_fee_cents"] == 549
    assert order["delivery_fee_cents"] == expected["delivery_fee_cents"] == 275
    assert order["total_charge_cents"] == expected["total_charge_cents"] == 2975
    a.assert_cents(order["delivery_fee_cents"], "delivery_fee_cents")


def test_address_exactly_on_the_ring_counts_as_inside_and_is_edge_over_the_ceiling():
    """A point sitting precisely on a boundary edge is inside the ring, so the long
    drive makes it an edge address rather than an out-of-area one.

    PRD: "If the point lies exactly on an edge, meaning it is collinear with that edge's two endpoints and lies within the rectangle those endpoints bound, the point counts as **inside** and the walk stops there; a point sitting precisely on a boundary or on a vertex is never outside."
    Design: Corner/calculations/on_ring_address_is_inside_while_one_micro_degree_outside_is_out_of_zone
    """
    store, _zone_version = fx.bootstrap(clock=DEFAULT_CLOCK)
    payload = f.create_service_address_payload(
        store["id"], 39000000, -84200000, line1="1 Ring Rd", crosses_barrier=False
    )

    address = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )

    assert address["grid_miles"] == 13.33 == ADDRESS_GRID_MILES["E"]
    assert address["drive_time_estimate_minutes"] == 46 == ADDRESS_DRIVE_MINUTES["E"]
    assert address["drive_time_estimate_minutes"] > TEST_ZONE_MODEL["max_drive_time_minutes"]
    assert address["zone_state"] == "EDGE", "inside the ring but over the ceiling"
    assert address["effective_zone_state"] == "EDGE", "no override is in force"
    assert address["override_state"] is None
    assert fx.read_address(address["id"])["effective_zone_state"] == "EDGE"


def test_address_one_micro_degree_outside_the_ring_is_out_of_zone_at_the_same_distance():
    """Shifting the point one micro-degree past the boundary flips the verdict to
    out-of-area even though the modelled mileage and drive time are unchanged.

    PRD: "A point that is not inside the ring is `OUT_OF_ZONE` however short its modelled drive may be."
    Design: Corner/calculations/on_ring_address_is_inside_while_one_micro_degree_outside_is_out_of_zone
    """
    store, _zone_version = fx.bootstrap(clock=DEFAULT_CLOCK)
    on_ring = fx.add_address_at(
        store["id"], 39000000, -84200000, line1="1 Ring Rd", crosses_barrier=False
    )
    payload = f.create_service_address_payload(
        store["id"], 39000000, -84200001, line1="2 Ring Rd", crosses_barrier=False
    )

    outside = validate_success(
        api_client.create_service_address(payload, DISPATCHER_HEADERS), 201
    )

    assert outside["grid_miles"] == on_ring["grid_miles"] == 13.33
    assert outside["drive_time_estimate_minutes"] == on_ring["drive_time_estimate_minutes"] == 46
    assert on_ring["zone_state"] == "EDGE"
    assert outside["zone_state"] == "OUT_OF_ZONE", "one micro-degree past the edge"
    assert outside["effective_zone_state"] == "OUT_OF_ZONE"
    assert outside["override_state"] is None
    assert fx.read_address(outside["id"])["effective_zone_state"] == "OUT_OF_ZONE"


def test_full_waiver_zeroes_the_charged_delivery_fee_at_the_three_thousand_cent_subtotal():
    """A 3000-cent food subtotal earns a 100 percent waiver, so the charged fee is
    exactly zero while the base fee still records what the tier would have cost.

    PRD: "The fourth step computes the `delivery_fee_cents` actually charged by multiplying `base_delivery_fee_cents` by the complement of the waiver percentage — that is, by 100 minus `fee_waiver_pct` — dividing by 100, and rounding the result half up to a whole cent."
    Design: Corner/calculations/full_waiver_at_the_three_thousand_cent_threshold_zeroes_the_delivery_fee
    """
    store, _zone_version = fx.bootstrap(clock=NOON_CLOCK)
    address = fx.add_address(store["id"], "A")
    assert address["drive_time_estimate_minutes"] == 15
    payload = f.create_order_payload(
        store["id"],
        address["id"],
        food_subtotal_cents=WAIVER_FULL_THRESHOLD_CENTS,
        tip_cents=500,
        payment_method="CARD",
    )

    order = validate_success(api_client.create_order(payload, DISPATCHER_HEADERS), 201)

    a.assert_order(order)
    assert order["fee_tier"] == "BASE", "a 15-minute estimate is the base tier"
    assert order["base_delivery_fee_cents"] == 399, "the store fee plus a 0 surcharge"
    assert order["fee_waiver_pct"] == 100
    assert order["delivery_fee_cents"] == 0, "399 * (100 - 100) / 100"
    a.assert_cents(order["delivery_fee_cents"], "delivery_fee_cents")
    assert order["total_charge_cents"] == 3500 == 3000 + 0 + 500, "the tip still stands"
    assert order == {**order, **a.expected_order_pricing(15, 399, 3000, 500)}


def test_half_waiver_threshold_is_inclusive_at_two_thousand_cents():
    """One cent below the half-waiver threshold pays the whole fee; the threshold
    itself pays half of it, rounded half up.

    PRD: "The third step picks `fee_waiver_pct` from `food_subtotal_cents` **alone** — the tip never counts toward a waiver threshold: a food subtotal of at least 3000 cents earns a waiver of 100, a subtotal of at least 2000 but under 3000 earns 50, and anything below 2000 earns 0."
    Design: Corner/calculations/waiver_thresholds_are_inclusive_so_1999_pays_full_fee_and_2000_pays_half
    """
    store, _zone_version = fx.bootstrap(clock=NOON_CLOCK)
    address = fx.add_address(store["id"], "A")
    below = fx.place_order(
        store["id"], address["id"], food_subtotal_cents=1999, tip_cents=0
    )
    assert below["fee_tier"] == "BASE"
    assert below["fee_waiver_pct"] == 0, "1999 is under the threshold"
    assert below["delivery_fee_cents"] == 399, "the whole base fee is charged"
    assert below["total_charge_cents"] == 2398 == 1999 + 399 + 0
    payload = f.create_order_payload(
        store["id"],
        address["id"],
        food_subtotal_cents=WAIVER_HALF_THRESHOLD_CENTS,
        tip_cents=0,
    )

    at_threshold = validate_success(
        api_client.create_order(payload, DISPATCHER_HEADERS), 201
    )

    assert at_threshold["fee_tier"] == "BASE"
    assert at_threshold["fee_waiver_pct"] == 50, "at least 2000 earns the half waiver"
    assert at_threshold["fee_waiver_pct"] == a.expected_waiver_pct(2000)
    assert at_threshold["delivery_fee_cents"] == 200, "399 * 50 / 100 is 199.5, half up"
    assert at_threshold["delivery_fee_cents"] == a.round_half_up(399 * 50 / 100)
    a.assert_cents(at_threshold["delivery_fee_cents"], "delivery_fee_cents")
    assert at_threshold["total_charge_cents"] == 2200 == 2000 + 200 + 0


def test_far_tier_adds_the_three_hundred_fifty_cent_surcharge_to_the_base_fee():
    """A 27-minute estimate is the far tier, so the base fee is the store's own fee
    plus the far surcharge.

    PRD: "The second step computes `base_delivery_fee_cents` as the store's `delivery_fee_cents` plus that tier's surcharge, where the surcharge is 0 cents for `BASE`, 150 cents for `MID` and 350 cents for `FAR`."
    Design: Corner/calculations/delivery_fee_rounds_half_up_at_three_seventy_four_point_five_on_the_far_tier
    """
    store, _zone_version = fx.bootstrap(clock=NOON_CLOCK)
    address = fx.add_address_at(
        store["id"], 39066650, -84033325, line1="665 Halfway Ln", crosses_barrier=False
    )
    assert address["drive_time_estimate_minutes"] == 27, "above the 25-minute cut"
    payload = f.create_order_payload(
        store["id"], address["id"], food_subtotal_cents=2500, tip_cents=300
    )

    order = validate_success(api_client.create_order(payload, DISPATCHER_HEADERS), 201)

    assert order["fee_tier"] == "FAR"
    assert order["base_delivery_fee_cents"] == 749 == 399 + FEE_TIER_SURCHARGE_CENTS["FAR"]
    a.assert_cents(order["base_delivery_fee_cents"], "base_delivery_fee_cents")
    assert order["base_delivery_fee_cents"] == a.expected_order_pricing(27, 399, 2500, 300)[
        "base_delivery_fee_cents"
    ]


def test_charged_fee_rounds_half_up_at_three_hundred_seventy_four_and_a_half_cents():
    """Halving a 749-cent base fee lands exactly on a half cent, and the charge
    rounds up to 375 rather than down to 374.

    PRD: "Where a monetary computation produces a fractional intermediate value, that value is rounded **half up** to a whole number of cents — a value ending in exactly one half rounds away from zero, so 199.5 becomes 200 and 274.5 becomes 275."
    Design: Corner/calculations/delivery_fee_rounds_half_up_at_three_seventy_four_point_five_on_the_far_tier
    """
    store, _zone_version = fx.bootstrap(clock=NOON_CLOCK)
    address = fx.add_address_at(
        store["id"], 39066650, -84033325, line1="665 Halfway Ln", crosses_barrier=False
    )
    payload = f.create_order_payload(
        store["id"], address["id"], food_subtotal_cents=2500, tip_cents=300
    )

    order = validate_success(api_client.create_order(payload, DISPATCHER_HEADERS), 201)

    assert order["fee_waiver_pct"] == 50
    assert 749 * (100 - 50) / 100 == 374.5, "the intermediate sits on a half cent"
    assert order["delivery_fee_cents"] == 375, "half up, not down to 374"
    assert order["delivery_fee_cents"] == a.round_half_up(374.5)
    assert order["delivery_fee_cents"] != 374, "truncation is not the rule"
    a.assert_cents(order["delivery_fee_cents"], "delivery_fee_cents")
    assert order["total_charge_cents"] == 3175 == 2500 + 375 + 300


def test_publishing_a_later_schedule_retires_the_earlier_one_for_the_same_vehicle_class():
    """Publishing an August schedule retires the July one for the same vehicle
    class, stamping its retirement from the logical clock.

    PRD: "A published schedule is stored `ACTIVE` with `retired_at` null, and publishing it retires the store's earlier work: any schedule for the same store and the same `vehicle_class` that is currently `ACTIVE` and whose `effective_from` is earlier than the new one's becomes `RETIRED`, with `retired_at` stamped from the logical clock."
    Design: Corner/calculations/cost_model_selection_ignores_the_retired_earlier_schedule
    """
    world = fx.setup_operational_store(
        clock=NOON_CLOCK, address_keys=(), with_driver=False
    )
    store_id = world["store"]["id"]
    july = world["cost_model"]
    assert july["status"] == "ACTIVE" and july["retired_at"] is None
    payload = f.create_vehicle_cost_model_payload(
        store_id,
        per_delivery_cents=200,
        tier1_per_mile_cents=70,
        tier2_per_mile_cents=45,
        effective_from="2026-08-01T00:00:00Z",
    )

    august = validate_success(
        api_client.create_vehicle_cost_model(payload, make_manager_headers(store_id)), 201
    )

    a.assert_vehicle_cost_model(august)
    assert august["status"] == "ACTIVE" and august["retired_at"] is None
    retired = validate_success(
        api_client.get_vehicle_cost_model(july["id"], world["manager_headers"]), 200
    )
    assert retired["status"] == "RETIRED", "the earlier August-preceding schedule retires"
    a.assert_iso_millis(retired["retired_at"], "retired_at")
    assert a.parse_instant(retired["retired_at"]) == a.parse_instant(NOON_CLOCK)
    listed, meta = validate_paginated(
        api_client.list_vehicle_cost_models(
            world["manager_headers"],
            {"store_id": store_id, "vehicle_class": "CAR", "status": "ACTIVE"},
        )
    )
    assert meta["total_count"] == 1, "only one schedule per class stays in force"
    assert [row["id"] for row in listed] == [august["id"]]


def test_lock_resolves_the_active_schedule_and_prices_the_route_at_its_rates():
    """The selector only looks at schedules still in force, so the committed route
    is priced at the August rates and never at the retired July ones.

    PRD: "The selector considers every vehicle cost model whose `store_id` matches the driver's store, whose `vehicle_class` matches the driver's `vehicle_class`, whose `status` is `ACTIVE`, and whose `effective_from` is at or before the route's `planned_depart_at`."
    Design: Corner/calculations/cost_model_selection_ignores_the_retired_earlier_schedule
    """
    world = fx.setup_operational_store(clock=NOON_CLOCK, address_keys=("A",))
    store_id = world["store"]["id"]
    july = world["cost_model"]
    august = fx.add_cost_model(
        store_id,
        per_delivery_cents=200,
        tier1_per_mile_cents=70,
        tier2_per_mile_cents=45,
        effective_from="2026-08-01T00:00:00Z",
    )
    order = fx.add_ready_order(store_id, world["addresses"]["A"]["id"])
    dispatch = fx.open_dispatch(world["driver"]["id"], DEPART_AT)
    fx.stack_stop(dispatch["id"], order["id"])

    locked = validate_success(
        api_client.lock_dispatch(dispatch["id"], DISPATCHER_HEADERS), 200
    )

    a.assert_dispatch(locked)
    assert locked["status"] == "LOCKED"
    assert locked["resolved_cost_model_id"] == august["id"]
    assert locked["resolved_cost_model_id"] != july["id"], "the retired one is ignored"
    assert locked["estimated_reimbursement_cents"] == 410, "200 + 3.00 * 70 cents"
    assert locked["estimated_reimbursement_cents"] == 200 + a.round_half_up(3.00 * 70)
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], august
    )
    assert a.expected_reimbursement_from_model([3.00], july) == 336, "the July price"
    assert locked["estimated_reimbursement_cents"] != 336
    a.assert_cents(locked["estimated_reimbursement_cents"], "estimated_reimbursement_cents")


def test_route_minutes_repeat_the_last_leg_as_the_drive_home():
    """Two 3.00-mile stops model at nine out, nine out, twelve of handoff and a
    nine-minute home leg, so the return is expected 39 minutes after departure.

    PRD: "The homeward component is modelled as a repeat of the last counted stop's outbound leg: that stop's `planned_miles` multiplied by `minutes_per_mile` and rounded up to the next whole minute."
    Design: Corner/calculations/route_duration_charges_the_final_leg_twice_on_a_two_stop_route
    """
    world = fx.setup_stacked_route(
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        order_overrides=[{}, {"tip_cents": 0}],
    )
    assert world["store"]["handoff_minutes_per_stop"] == 6
    assert [stop["planned_miles"] for stop in world["stops"]] == [3.00, 3.00]

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert locked["route_minutes"] == 39, "9 + 9 outbound, 12 handoff, 9 home"
    assert locked["route_minutes"] == a.expected_route_minutes(
        [3.00, 3.00], TEST_ZONE_MODEL["minutes_per_mile"], 6
    )
    assert locked["route_minutes"] != 30, "the home leg is never dropped"
    a.assert_iso_millis(locked["expected_return_at"], "expected_return_at")
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(DEPART_AT, minutes=39)
    )
    assert locked["stop_count"] == 2
    assert locked["committed_hot_bag_slots"] == 2


def test_two_identical_stops_earn_different_money_from_the_cumulative_tier_one_cap():
    """The five-mile tier-one allowance is consumed across the whole route, so the
    second of two identical stops is paid less than the first.

    PRD: "What the store owes a driver for a route is computed stop by stop, in `sequence` ascending order, and the order is observable because the tier-1 mileage allowance is consumed **cumulatively across the whole route** rather than reset at each stop."
    Design: Corner/calculations/route_duration_charges_the_final_leg_twice_on_a_two_stop_route
    """
    world = fx.setup_stacked_route(
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        order_overrides=[{}, {"tip_cents": 0}],
    )
    cost_model = world["cost_model"]
    assert cost_model["tier1_cap_miles"] == 5.0

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert a.expected_stops_from_model([3.00, 3.00], cost_model) == [336, 315]
    assert locked["estimated_reimbursement_cents"] == 651 == 336 + 315
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00, 3.00], cost_model
    )
    assert locked["estimated_reimbursement_cents"] != 672, "the allowance is not reset"
    a.assert_cents(locked["estimated_reimbursement_cents"], "estimated_reimbursement_cents")


def test_per_stop_minimum_floors_the_quarter_mile_stop_to_the_schedule_floor():
    """A quarter-mile stop earns 15.5 cents of mileage, which rounds to 16 and is
    then raised to the 100-cent per-stop minimum.

    PRD: "**Round that subtotal half up to a whole number of cents, then raise it to `min_reimbursement_per_stop_cents` if it falls below that floor, and only then add it to the running total** — the rounding happens once per stop, the floor is applied after the rounding, and the summation happens after both."
    Design: Corner/calculations/per_stop_minimum_floors_a_quarter_mile_leg_to_one_hundred_cents
    """
    world = fx.setup_stacked_route(
        ("P",),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        cost_model_overrides={"per_delivery_cents": 0},
    )
    assert world["addresses"]["P"]["grid_miles"] == 0.25
    assert world["addresses"]["P"]["drive_time_estimate_minutes"] == 7
    cost_model = world["cost_model"]
    assert cost_model["per_delivery_cents"] == 0
    assert cost_model["min_reimbursement_per_stop_cents"] == 100

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert 0.25 * 62 == 15.5, "the raw mileage subtotal sits on a half cent"
    assert a.round_half_up(15.5) == 16, "the rounding happens before the floor"
    assert locked["estimated_reimbursement_cents"] == 100, "the floor lifts the stop"
    assert locked["estimated_reimbursement_cents"] != 16, "the floor still applies"
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [0.25], cost_model
    )
    a.assert_cents(locked["estimated_reimbursement_cents"], "estimated_reimbursement_cents")
    lines, meta = validate_paginated(
        api_client.list_reimbursement_lines(
            world["manager_headers"], {"dispatch_id": world["dispatch"]["id"]}
        )
    )
    assert meta["total_count"] == 0 and lines == [], "commitment writes no ledger line"


def test_route_minutes_round_each_leg_up_individually_on_a_quarter_mile_stop():
    """A 0.75-minute leg is rounded up to a whole minute on the way out and again
    on the way home, so the quarter-mile round trip models at eight minutes.

    PRD: "The outbound component is the sum, over counted stops in `sequence` ascending order, of each stop's `planned_miles` multiplied by the in-force delivery-area version's `minutes_per_mile` and rounded up to the next whole minute — the rounding-up is applied to each leg individually, before the legs are added together, never to the sum."
    Design: Corner/calculations/per_stop_minimum_floors_a_quarter_mile_leg_to_one_hundred_cents
    """
    world = fx.setup_stacked_route(
        ("P",),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        cost_model_overrides={"per_delivery_cents": 0},
    )
    assert world["stops"][0]["planned_miles"] == 0.25

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert 0.25 * TEST_ZONE_MODEL["minutes_per_mile"] == 0.75, "a partial minute per leg"
    assert locked["route_minutes"] == 8, "1 out, 6 of handoff, 1 home"
    assert locked["route_minutes"] == a.expected_route_minutes(
        [0.25], TEST_ZONE_MODEL["minutes_per_mile"], 6
    )
    assert locked["route_minutes"] != 7, "each leg rounds up on its own"
    assert a.parse_instant(locked["expected_return_at"]) == a.parse_instant(
        a.instant_plus(DEPART_AT, minutes=8)
    )


def test_released_stop_consumes_no_tier_one_room_in_the_estimate():
    """Releasing the first of two identical stops restarts the waterfall for the
    survivor, which is therefore paid the first-stop price.

    PRD: "The **estimated** variant counts stops whose status is `PENDING`, `DELIVERED` or `REMADE` and uses each stop's `planned_miles`; it is what fills the route's `estimated_reimbursement_cents` at commitment time and what prices each provisional ledger line written at a door."
    Design: Corner/calculations/estimated_reimbursement_excludes_a_released_stop_and_restarts_the_waterfall
    """
    world = fx.setup_stacked_route(
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        order_overrides=[{}, {"tip_cents": 0}],
    )
    fx.unstack_stop(world["dispatch"]["id"], world["stops"][0]["id"])

    locked = validate_success(
        api_client.lock_dispatch(world["dispatch"]["id"], DISPATCHER_HEADERS), 200
    )

    assert locked["stop_count"] == 1, "the released stop stops being counted"
    assert locked["estimated_reimbursement_cents"] == 336, "150 + 3.00 * 62 cents"
    assert locked["estimated_reimbursement_cents"] == a.expected_reimbursement_from_model(
        [3.00], world["cost_model"]
    )
    assert locked["estimated_reimbursement_cents"] != 315, "no tier-1 room was spent"
    assert locked["route_minutes"] == 24, "9 out, 6 of handoff, 9 home"
    assert locked["route_minutes"] == a.expected_route_minutes(
        [3.00], TEST_ZONE_MODEL["minutes_per_mile"], 6
    )


def test_un_stacking_returns_the_route_totals_and_leaves_the_surviving_sequence_alone():
    """Un-stacking releases the stop, hands its order back to the ready pool and
    returns both route totals to their pre-insertion values without renumbering.

    PRD: "The stop's status becomes `RELEASED`, its order reverts `ASSIGNED → READY`, and the route's `committed_hot_bag_slots` and `stop_count` both fall back to their pre-insertion values — the hot-bag pool must return to exactly the total it had before, which is why released stops stop being counted."
    Design: Corner/calculations/estimated_reimbursement_excludes_a_released_stop_and_restarts_the_waterfall
    """
    world = fx.setup_stacked_route(
        ("A", "A"),
        clock=NOON_CLOCK,
        planned_depart_at=DEPART_AT,
        order_overrides=[{}, {"tip_cents": 0}],
    )
    first, second = world["stops"]
    assert [first["sequence"], second["sequence"]] == [1, 2]
    assert world["dispatch"]["stop_count"] == 2
    assert world["dispatch"]["committed_hot_bag_slots"] == 2

    route = validate_success(
        api_client.delete_dispatch_stop(
            world["dispatch"]["id"], first["id"], DISPATCHER_HEADERS
        ),
        200,
    )

    a.assert_dispatch(route)
    assert route["stop_count"] == 1
    assert route["committed_hot_bag_slots"] == 1, "the bags go back on the shelf"
    released = fx.read_stop(first["id"])
    assert released["status"] == "RELEASED"
    assert released["sequence"] == 1, "the ordinal is not reused"
    assert fx.read_order(world["orders"][0]["id"])["fulfillment_status"] == "READY"
    survivor = fx.read_stop(second["id"])
    assert survivor["status"] == "PENDING" and survivor["sequence"] == 2


def test_order_to_door_gross_truncates_the_partly_elapsed_minute():
    """An order handed over one second before the thirty-seventh minute completes
    reads 36 gross minutes, because the partly elapsed minute is not yet counted.

    PRD: "`order_to_door_gross_minutes` is what the customer experienced: the difference between the order's `door_arrival_at` and its `placed_at`, taken in whole seconds, divided by 60 and truncated downward, so a partly elapsed minute is not yet counted."
    Design: Corner/calculations/order_to_door_gross_floors_a_partially_elapsed_minute
    """
    world = fx.setup_departed_route(
        ("A",), clock=NOON_CLOCK, planned_depart_at=DEPART_AT
    )
    order_id = world["orders"][0]["id"]
    assert world["orders"][0]["promise_minutes_snapshot"] == 30
    assert a.parse_instant(world["orders"][0]["placed_at"]) == a.parse_instant(NOON_CLOCK)
    fx.set_clock("2026-08-05T12:36:59Z")

    validate_success(
        api_client.door_arrival(
            world["dispatch"]["id"],
            world["stops"][0]["id"],
            f.door_arrival_payload(3.4, 0),
            make_driver_headers(world["driver"]["id"]),
        ),
        200,
    )

    order = fx.read_order(order_id)
    a.assert_iso_millis(order["door_arrival_at"], "door_arrival_at")
    assert a.parse_instant(order["door_arrival_at"]) == a.parse_instant(
        "2026-08-05T12:36:59Z"
    )
    assert order["order_to_door_gross_minutes"] == 36, "2219 seconds is 36 whole minutes"
    assert order["order_to_door_gross_minutes"] != 37, "the last minute is incomplete"
    assert order["order_to_door_gross_minutes"] == a.whole_minutes_between(
        order["placed_at"], order["door_arrival_at"]
    )
    assert order["zone_hold_minutes"] == 0 and order["remake_hold_minutes"] == 0
    assert order["order_to_door_net_minutes"] == 36, "no holds to remove"
    a.assert_order_to_door(order)
    assert order["fulfillment_status"] == "DELIVERED"
    assert order["settlement_status"] == "CHARGED"
    assert fx.read_stop(world["stops"][0]["id"])["status"] == "DELIVERED"


def test_late_remedy_pays_twenty_percent_of_the_food_subtotal_with_no_fee_refund():
    """An order six minutes past its promise sits in the lowest late tier, so the
    proposal is a fifth of the food subtotal and the delivery fee is not refunded.

    PRD: "For a `LATE` complaint, compute how many minutes the order ran over by subtracting the order's `promise_minutes_snapshot` from its `order_to_door_gross_minutes`; if that overage is 20 minutes or more, the food percentage is 100 and the whole `delivery_fee_cents` is additionally refunded; if the overage is at least 10 but under 20, the percentage is 50 and no fee is refunded; if the overage is at least 1 but under 10, the percentage is 20 and no fee is refunded; and if the order was not late at all the percentage is 0 with no fee refund."
    Design: Corner/calculations/late_complaint_remedy_pays_tier_one_percent_of_the_food_subtotal
    """
    world = fx.setup_departed_route(
        ("A",), clock=NOON_CLOCK, planned_depart_at=DEPART_AT
    )
    fx.set_clock("2026-08-05T12:36:00Z")
    fx.arrive_at_door(
        world["dispatch"]["id"],
        world["stops"][0]["id"],
        world["driver"]["id"],
        3.4,
        0,
    )
    order = fx.read_order(world["orders"][0]["id"])
    assert order["food_subtotal_cents"] == 2200
    assert order["delivery_fee_cents"] == 200
    assert order["total_charge_cents"] == 2900
    assert order["order_to_door_gross_minutes"] == 36
    assert order["promise_minutes_snapshot"] == 30, "the order ran 6 minutes over"
    complaint = fx.log_complaint(
        order["id"], "LATE", description="Pizza arrived cold and late"
    )
    assert complaint["status"] == "OPEN"
    assert complaint["proposed_remedy_cents"] is None
    assert complaint["remedy_basis"] is None

    proposed = validate_success(
        api_client.propose_remedy(complaint["id"], CARE_HEADERS), 200
    )

    a.assert_complaint(proposed)
    assert proposed["status"] == "REMEDY_PROPOSED"
    assert proposed["proposed_remedy_cents"] == 440, "2200 * 20 / 100"
    assert proposed["proposed_remedy_cents"] == a.round_half_up(2200 * 20 / 100)
    assert proposed["proposed_remedy_cents"] != 640, "the fee is not refunded in this tier"
    a.assert_cents(proposed["proposed_remedy_cents"], "proposed_remedy_cents")
    assert proposed["remedy_basis"] == "LATE_TIER"
    assert (proposed["proposed_remedy_cents"], proposed["remedy_basis"]) == a.expected_remedy(
        order, "LATE"
    )
    assert a.expected_late_remedy_cents(2200, 36, 30, 200) == 440
    assert fx.read_order(order["id"])["remedy_issued_cents"] == 0, "nothing is issued yet"
