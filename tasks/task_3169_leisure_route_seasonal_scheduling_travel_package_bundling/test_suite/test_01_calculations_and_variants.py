"""Difficulty queue A — rules 1 (dual variant) and 2 (combinatorial formula).

Covers instances:
- dual_variant_calc / settlement_provisional_vs_final_diverges_on_cancelled_bundle (x2)
- dual_variant_calc / base_fare_snapshot_vs_live_route_fare (x2)
- combinatorial_formula / utilization_cap_multibranch_peak_vs_nonpeak (x2)
- combinatorial_formula / settlement_rounding_order_pinned_sum_then_store (x2)
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_origin_station,
    create_package_booking,
    create_provisional_settlement,
    create_route,
    create_supplier_offer,
    get_booking,
    get_bundle,
    get_flight,
    get_settlement,
    set_default_clock,
    setup_published_pipeline,
    setup_settlement_with_package_bookings,
    setup_station_pair,
    validate_error,
    validate_success,
)

NP = TEST_USERS["network_planner_headers"]
OC = TEST_USERS["ops_controller_headers"]
CS = TEST_USERS["customer_service_headers"]
FA = TEST_USERS["finance_analyst_headers"]


# ---------------------------------------------------------------------------
# dual_variant_calc / settlement_provisional_vs_final_diverges_on_cancelled_bundle
# ---------------------------------------------------------------------------


def test_settlement_provisional_counts_cancelled_bundle(api):
    """PRD §3.8: "its `gross_payable_cents` is computed under the provisional
    variant: it sums the `net_cost_cents` of the supplier's offer for every
    package bundle that consumes one of that supplier's offers, whose
    `bundle_status` is either `ACTIVE` or `CANCELLED`, and whose booking's
    flight date falls within the settlement period inclusive of both end
    dates."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverges_on_cancelled_bundle
    """
    ctx = setup_settlement_with_package_bookings(num_bookings=2)
    api.cancel_booking(ctx["bookings"][0]["id"], CS)

    settlement = create_provisional_settlement("HTL-SFB-1")
    assert settlement["settlement_status"] == "PROVISIONAL"
    assert settlement["clawback_cents"] == 0
    # Both bundles count under the provisional variant: 2 * 12000.
    assert settlement["gross_payable_cents"] == 24000, (
        f"Expected provisional gross 24000, got {settlement['gross_payable_cents']}"
    )


def test_settlement_final_variant_diverges_from_provisional(api):
    """PRD §3.8: "At finalization the gross payable is recomputed under the
    final variant: the same window applies, but only bundles whose
    `bundle_status` is still `ACTIVE` at finalization are counted. Bundles
    that were cancelled between the provisional run and finalization are
    excluded from the gross, and their value lives in the settlement's
    `clawback_cents` instead."

    Design: Difficulty/dual_variant_calc/settlement_provisional_vs_final_diverges_on_cancelled_bundle
    """
    ctx = setup_settlement_with_package_bookings(num_bookings=2)
    api.cancel_booking(ctx["bookings"][0]["id"], CS)
    settlement = create_provisional_settlement("HTL-SFB-1")
    assert settlement["gross_payable_cents"] == 24000

    # Advance the logical clock strictly past period_end_date, then finalize.
    resp = api.set_clock("2027-04-01T00:00:00Z", FA)
    assert resp.status_code == 200
    final = validate_success(api.finalize_supplier_settlement(settlement["id"], FA))

    assert final["settlement_status"] == "FINALIZED"
    # Only the still-ACTIVE bundle counts under the final variant.
    assert final["gross_payable_cents"] == 12000, (
        f"Expected final gross 12000, got {final['gross_payable_cents']}"
    )
    # The bundle was cancelled BEFORE this settlement existed, so no
    # cancel-while-PROVISIONAL clawback event ever fired on it.
    assert final["clawback_cents"] == 0, (
        f"Expected final clawback 0, got {final['clawback_cents']}"
    )
    # The two variants diverge on identical window data.
    assert final["gross_payable_cents"] != 24000


# ---------------------------------------------------------------------------
# dual_variant_calc / base_fare_snapshot_vs_live_route_fare
# ---------------------------------------------------------------------------


def test_booking_base_fare_total_is_pinned_snapshot(api):
    """PRD §3.5: "The booking's `base_fare_total_cents` is computed at creation
    as the `passenger_count` multiplied by the route's `base_fare_cents`, and
    that product is pinned onto the booking row as a snapshot: a later change
    to the route's base fare does not retroactively modify existing bookings."

    Design: Difficulty/dual_variant_calc/base_fare_snapshot_vs_live_route_fare
    """
    ctx = setup_published_pipeline()
    booking = validate_success(
        api.create_booking(
            {
                "flight_instance_id": ctx["flights"][0]["id"],
                "passenger_count": 2,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": ctx["flights"][0]["version"],
            },
            CS,
        ),
        expected_status=201,
    )
    # 2 * 9900 — the product pinned at booking time.
    assert booking["base_fare_total_cents"] == 19800, (
        f"Expected base_fare_total_cents 19800, got {booking['base_fare_total_cents']}"
    )
    # The pinned value survives re-read.
    reread = get_booking(booking["id"])
    assert reread["base_fare_total_cents"] == 19800


def test_air_only_booking_has_zero_ancillary_and_no_bundle(api):
    """PRD §3.5: "The booking's `ancillary_total_cents` begins at zero." and
    "A new booking's `booking_status` begins at `CONFIRMED`, with
    `stranded_until_date` null and `package_bundle_id` null for an air-only
    booking."

    Design: Difficulty/dual_variant_calc/base_fare_snapshot_vs_live_route_fare
    """
    ctx = setup_published_pipeline()
    booking = validate_success(
        api.create_booking(
            {
                "flight_instance_id": ctx["flights"][0]["id"],
                "passenger_count": 2,
                "booking_kind": "AIR_ONLY",
                "expected_flight_version": ctx["flights"][0]["version"],
            },
            CS,
        ),
        expected_status=201,
    )
    assert booking["booking_kind"] == "AIR_ONLY"
    assert booking["ancillary_total_cents"] == 0
    assert booking.get("package_bundle_id") is None
    assert booking.get("stranded_until_date") is None
    assert booking["booking_status"] == "CONFIRMED"


# ---------------------------------------------------------------------------
# combinatorial_formula / utilization_cap_multibranch_peak_vs_nonpeak
# ---------------------------------------------------------------------------


def test_utilization_check_uses_nonpeak_cap_for_nonpeak_day(api):
    """PRD §3.3: "The applicable cap is `peak_day_cap_minutes` when the target
    flight's `is_peak_day` flag is `true`, and `daily_utilization_cap_minutes`
    otherwise. If the proposed total is strictly greater than the applicable
    cap, the assignment is rejected with `ERR_UTILIZATION_CAP_EXCEEDED`
    (HTTP 409)."

    Design: Difficulty/combinatorial_formula/utilization_cap_multibranch_peak_vs_nonpeak
    """
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-29",
        assign_aircraft_to="none",
    )
    flights = ctx["flights"]
    assert len(flights) >= 2, "need two Monday flights"
    # First assignment on 2027-03-01 uses the non-peak branch.
    first = validate_success(
        api.assign_aircraft(flights[0]["id"], {"aircraft_id": ctx["aircraft"]["id"]}, OC)
    )
    assert first["aircraft_id"] == ctx["aircraft"]["id"]
    assert first["is_peak_day"] is False


def test_utilization_accumulates_per_date_not_across_dates(api):
    """PRD §3.3: "it sums `block_minutes` across every still-`SCHEDULED` flight
    already assigned to that aircraft whose `flight_date` equals the target
    flight's `flight_date`, then adds the target flight's own `block_minutes`
    to form the proposed total for the day."

    Design: Difficulty/combinatorial_formula/utilization_cap_multibranch_peak_vs_nonpeak
    """
    ctx = setup_published_pipeline(
        operating_days_mask=[1],
        first_operating_date="2027-03-01",
        last_operating_date="2027-03-29",
        assign_aircraft_to="none",
    )
    flights = ctx["flights"]
    # Assign flight 1 (240 of 480 non-peak minutes on 2027-03-01).
    api.assign_aircraft(flights[0]["id"], {"aircraft_id": ctx["aircraft"]["id"]}, OC)
    # Flight 2 is on a different date (2027-03-08): day_minutes there is 0,
    # so proposed 240 <= 480 succeeds.
    second = validate_success(
        api.assign_aircraft(flights[1]["id"], {"aircraft_id": ctx["aircraft"]["id"]}, OC)
    )
    assert second["aircraft_id"] == ctx["aircraft"]["id"]
    assert second["is_peak_day"] is False


# ---------------------------------------------------------------------------
# combinatorial_formula / settlement_rounding_order_pinned_sum_then_store
# ---------------------------------------------------------------------------


def _setup_three_bundle_scenario(api):
    """Pipeline + three offers from one supplier + three PACKAGE bookings with
    growing component sets. Returns (ctx, bundles)."""
    ctx = setup_published_pipeline()
    dest_id = ctx["destination"]["id"]
    off_h = create_supplier_offer(
        dest_id, supplier_code="SUP-X", component_kind="HOTEL",
        net_cost_cents=10000, sell_price_cents=18000,
    )
    off_c = create_supplier_offer(
        dest_id, supplier_code="SUP-X", component_kind="RENTAL_CAR",
        net_cost_cents=4000, sell_price_cents=7500,
    )
    off_t = create_supplier_offer(
        dest_id, supplier_code="SUP-X", component_kind="ATTRACTION_TICKET",
        net_cost_cents=1500, sell_price_cents=3000,
    )
    flight = ctx["flights"][0]
    bk_h = create_package_booking(flight, off_h["id"])
    bk_hc = create_package_booking(
        flight, off_h["id"], rental_car_offer_id=off_c["id"]
    )
    bk_hct = create_package_booking(
        flight, off_h["id"],
        rental_car_offer_id=off_c["id"], attraction_offer_id=off_t["id"],
    )
    bundles = [
        get_bundle(bk_h["package_bundle_id"]),
        get_bundle(bk_hc["package_bundle_id"]),
        get_bundle(bk_hct["package_bundle_id"]),
    ]
    return ctx, bundles


def test_bundle_price_sums_components_in_pinned_order(api):
    """PRD §3.5: "The bundle's `bundle_price_cents` is computed at creation as
    the sum of the `sell_price_cents` of the included components: first each
    offer's sell price is resolved and frozen at booking time, then the prices
    are summed in the order hotel, then rental car, then attraction, and the
    result is stored as integer cents with no rounding needed because every
    input is already integer cents."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_pinned_sum_then_store
    """
    _, bundles = _setup_three_bundle_scenario(api)
    assert bundles[0]["bundle_price_cents"] == 18000
    assert bundles[1]["bundle_price_cents"] == 25500  # 18000 + 7500
    assert bundles[2]["bundle_price_cents"] == 28500  # 18000 + 7500 + 3000


def test_settlement_gross_sums_per_bundle_net_costs(api):
    """PRD §3.8: "its `gross_payable_cents` is computed under the provisional
    variant: it sums the `net_cost_cents` of the supplier's offer for every
    package bundle that consumes one of that supplier's offers, whose
    `bundle_status` is either `ACTIVE` or `CANCELLED`, and whose booking's
    flight date falls within the settlement period inclusive of both end
    dates."

    Design: Difficulty/combinatorial_formula/settlement_rounding_order_pinned_sum_then_store
    """
    _, _ = _setup_three_bundle_scenario(api)
    settlement = create_provisional_settlement("SUP-X")
    # Per-bundle net sums: 10000 + 14000 + 15500 = 39500.
    assert settlement["gross_payable_cents"] == 39500, (
        f"Expected gross 39500, got {settlement['gross_payable_cents']}"
    )
