"""Formulas whose two possible metrics disagree on the same data."""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_freeze_in_state,
    create_itinerary,
    create_route,
    get_success_data,
    observe,
    publish_curve,
    read_freeze,
    set_clock,
)


def test_guarantee_ceiling_takes_the_larger_of_the_manifest_and_cap_ceilings():
    """PRD §3.3: "It also fills the three tier ceilings described in §2.8:
    `firm_tier_ceiling_cents`, the ceiling of the most recent observed fare at
    or before filing; `cap_tier_ceiling_cents`, the ceiling of `cap_cents`; and
    `guaranteed_ceiling_cents`, the larger of the two." PRD §2.8: "an amount
    below 20000 maps to 30000; an amount below 50000 maps to 50000".

    Design: Difficulty/combinatorial_formula/combinatorial_insurance_tier_boundary_straddle
    """
    set_clock()
    route = create_route(base_fare_cents=14286)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    got = read_freeze(freeze["id"])

    assert got["manifest_fare_cents"] == 14286
    assert got["cap_cents"] == pytest.approx(20000.00, abs=0.01), (
        "the cap is the manifest fare multiplied by 1.4 and rounded half-up"
    )
    assert got["cap_tier_ceiling_cents"] == 50000, (
        "a cap of exactly 20000 sits above the strict 20000 boundary, so it "
        "lands in the next tier up"
    )
    assert got["guaranteed_ceiling_cents"] == 50000


def test_a_fourteen_cent_manifest_change_moves_the_guarantee_by_a_full_tier():
    """PRD §2.8: "an amount of exactly 200000 cents lands in the
    200000-to-299999 tier and therefore maps to 200000, not 300000." PRD §3.3:
    "sets `cap_cents` to the manifest fare multiplied by 1.4 and rounded half-up
    to two decimal places".

    Design: Difficulty/combinatorial_formula/combinatorial_insurance_tier_boundary_straddle
    """
    set_clock()
    # 14286 * 1.4 = 20000.4 -> 20000, exactly on the tier boundary.
    low_route = create_route(base_fare_cents=14286)
    publish_curve(low_route["id"])
    low_itinerary = create_itinerary(low_route["id"], "tv-mara")
    low_freeze = create_freeze_in_state(low_itinerary["id"], "FROZEN", deposit_cents=250)

    # 14272 * 1.4 = 19980.8 -> 19981, fourteen cents of manifest lower and a
    # whole tier lower on the cap.
    high_route = create_route(base_fare_cents=14272)
    publish_curve(high_route["id"])
    high_itinerary = create_itinerary(high_route["id"], "tv-mara")
    high_freeze = create_freeze_in_state(high_itinerary["id"], "FROZEN", deposit_cents=250)

    low = read_freeze(low_freeze["id"])
    high = read_freeze(high_freeze["id"])
    assert low["cap_cents"] == pytest.approx(20000.00, abs=0.01)
    assert high["cap_cents"] == pytest.approx(19981.00, abs=0.01)
    assert low["cap_tier_ceiling_cents"] == 50000
    assert high["cap_tier_ceiling_cents"] == 30000, (
        "a cap below the strict 20000 boundary stays in the lower tier"
    )
    assert (low["guaranteed_ceiling_cents"] - high["guaranteed_ceiling_cents"]) == 20000, (
        "a fourteen-cent manifest difference changes the guarantee by a whole tier"
    )


def test_depth_ratio_is_the_unhedged_share_of_the_capped_impact():
    """PRD §2.10: "the unhedged exposure — the quantity that is aggregated into
    the region's pool — is the smaller of the exposure figure and the guaranteed
    ceiling, minus the hedged exposure." PRD §3.5: "The `depth_ratio` is the
    claimed freeze's `unhedged_exposure_cents` divided by its
    `capped_impact_cents`, rounded half-up to four decimal places and defined as
    0 when the denominator is 0".

    Design: Difficulty/combinatorial_formula/combinatorial_change_redemption_rate_metric_versus_duration_metric
    """
    set_clock()
    route = create_route(base_fare_cents=8900)
    publish_curve(route["id"])
    itinerary = create_itinerary(route["id"], "tv-mara")
    observe(route["id"], itinerary["id"], 10000, seats_left=6)
    freeze = create_freeze_in_state(itinerary["id"], "FROZEN", deposit_cents=250)
    got = read_freeze(freeze["id"])

    assert got["overshoot_cents"] == pytest.approx(1100.00, abs=0.01)
    assert got["exposure_cents"] == pytest.approx(1100.00, abs=0.01)
    assert got["capped_impact_cents"] == pytest.approx(1320.00, abs=0.01)
    assert got["hedged_exposure_cents"] == pytest.approx(660.00, abs=0.01)
    assert got["unhedged_exposure_cents"] == pytest.approx(440.00, abs=0.01)
    ratio = got["unhedged_exposure_cents"] / got["capped_impact_cents"]
    assert ratio == pytest.approx(0.3333, abs=0.0001), (
        "the depth ratio is the unhedged slice over the capped impact"
    )


def test_duration_metric_is_free_below_three_days_and_linear_after():
    """PRD §3.8: "a shift of zero days or fewer counts as 0, one day counts as
    1, two as 2, three as 3, and any shift of more than three days counts as
    three plus the number of extra days divided by two and rounded up to a whole
    day." PRD §3.8: "The metric is linear after the first three days rather than
    decaying, which makes a long shift expensive in whole-day terms."

    Design: Difficulty/combinatorial_formula/combinatorial_change_redemption_rate_metric_versus_duration_metric
    """
    set_clock()
    route = create_route(origin_airport="ORD", destination_airport="LHR",
                         flight_number="HA707", region="MIDWEST", base_fare_cents=13200,
                         peak_price_day_index=0, seats_left=6,
                         fare_band_cents=[9000, 12000, 15000, 17000, 19000])
    publish_curve(route["id"], each_day_prices_cents=[9000, 9000, 9000, 9000, 9000],
                  seats_left_at_each_day=[6, 6, 6, 6, 6])
    itinerary = create_itinerary(route["id"], "tv-otis", departure_date="2026-12-01T00:00:00Z")
    headers = TEST_USERS["traveler_otis_headers"]
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CHANGE",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            headers)
    )
    get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    change_event = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-13T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    assert change_event["day_shift"] == 12
    assert change_event["disruption_days"] == 8, (
        "a twelve-day shift counts as three plus one half of the nine extra days"
    )
    assert change_event["disruption_days"] != change_event["day_shift"], (
        "the duration metric is not the raw day distance"
    )


def test_a_twelve_day_shift_costs_eight_days_not_twelve():
    """PRD §3.8: "any shift of more than three days counts as three plus the
    number of extra days divided by two and rounded up to a whole day."

    Design: Difficulty/combinatorial_formula/combinatorial_change_redemption_rate_metric_versus_duration_metric
    """
    set_clock()
    route = create_route(origin_airport="ORD", destination_airport="LHR",
                         flight_number="HA707", region="MIDWEST", base_fare_cents=13200,
                         peak_price_day_index=0, seats_left=6,
                         fare_band_cents=[9000, 12000, 15000, 17000, 19000])
    publish_curve(route["id"], each_day_prices_cents=[9000, 9000, 9000, 9000, 9000],
                  seats_left_at_each_day=[6, 6, 6, 6, 6])
    itinerary = create_itinerary(route["id"], "tv-otis", departure_date="2026-12-01T00:00:00Z")
    headers = TEST_USERS["traveler_otis_headers"]
    protection = get_success_data(
        api_client.quote_protection(
            {"itinerary_id": itinerary["id"], "product_type": "CHANGE",
             "cancellation_disruption_probability": 0.70, "disclosure_version": 1,
             "disclosure_acknowledged": True},
            headers)
    )
    get_success_data(
        api_client.activate_protection(protection["id"],
                                       {"expected_protection_version": protection["version"]},
                                       headers)
    )
    three_day = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-04T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )
    get_success_data(
        api_client.cancel_change_event(three_day["id"], {"cancel_reason": "CHANGED_MIND"}, headers)
    )
    five_day = get_success_data(
        api_client.file_change_event(
            {"protection_id": protection["id"], "new_departure_date": "2026-12-06T00:00:00Z",
             "gap_direction": "ORIGIN_DIRECTION"},
            headers)
    )

    assert three_day["day_shift"] == 3 and three_day["disruption_days"] == 3, (
        "a three-day shift is still inside the free band"
    )
    assert five_day["day_shift"] == 5 and five_day["disruption_days"] == 4, (
        "one extra day of shift costs only one extra day of entitlement"
    )