"""Corner queue B: calculations (rate threshold, min-rides gate, exclusion
filtering, forecast approval semantics)."""

from test_helpers import (
    ADMIN,
    OPS,
    PAY,
    WEEK_MID,
    WEEK_START,
    activate_program,
    complete_ride_end_to_end,
    compute_settlement,
    create_active_challenge_program,
    create_active_guarantee_program,
    create_challenge_program,
    create_forecast_payload,
    create_guarantee_program,
    create_market_with_driver,
    create_streak_program,
    enroll,
    rate_events_payload,
    read_enrollment,
    read_program,
    set_clock,
    validate_success,
)


# ============================================================================
# corner: calculations
# ============================================================================
def test_posture_unchanged_below_min_offers_threshold(api):
    """PRD §3.2: "When offers_total is below 20 — the minimum-evidence constant
    — the posture is left unchanged regardless of what the rates say."
    PRD §3.2: "The acceptance rate in basis points is 10000 when offers_total
    is zero and otherwise the floor of 10000 times accepted_total divided by
    offers_total."

    Design: Corner/calculations/posture_unchanged_below_min_offers_threshold
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="MOB")
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=1, declined=18), OPS),
        200,
    )
    assert driver["offers_total"] == 19
    assert driver["acceptance_rate_bps"] == 526, (
        f"floor(10000*1/19) = 526, got {driver['acceptance_rate_bps']}"
    )
    assert driver["rate_posture"] == "ELIGIBLE", (
        f"19 < 20 means the posture is left unchanged, got "
        f"{driver['rate_posture']}"
    )


def test_guarantee_min_rides_not_met_yields_zero_makeup(api):
    """PRD §3.8: "make_up_cents is zero when qualifying_ride_count is below
    the program's guaranteed_min_rides and otherwise the larger of zero and
    promised_cents minus actual_gross_cents."

    Design: Corner/calculations/guarantee_min_rides_not_met_yields_zero_makeup
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="PNS", budget=10_000_000)
    program = create_active_guarantee_program(market["id"],
                                              guaranteed_weekly_cents=500_000,
                                              guaranteed_min_rides=2)
    enroll(program["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=50_000)

    settlement = validate_success(
        api.compute_settlement(
            {"driver_id": driver["id"], "program_id": program["id"],
             "week_start_utc": WEEK_START},
            PAY,
        ),
        201,
    )
    assert settlement["qualifying_ride_count"] == 1
    assert settlement["actual_gross_cents"] == 50_000
    assert settlement["make_up_cents"] == 0, (
        f"the ride-count gate dominates: 1 < 2 forces make_up 0, got "
        f"{settlement['make_up_cents']}"
    )


def test_excluded_ride_type_contributes_no_progress_and_no_guarantee_earnings(api):
    """PRD §3.3: "A ride whose ride_type appears in a program's
    excluded_ride_types earns neither progress nor payout under that program."
    PRD §3.6: "Evaluated per enrollment, a ride whose ride_type is in the
    covering program's excluded_ride_types contributes zero to that program's
    progress even when completed."

    Design: Corner/calculations/excluded_ride_type_contributes_no_progress_and_no_guarantee_earnings
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="TAH", budget=10_000_000)
    guarantee = create_active_guarantee_program(
        market["id"], guaranteed_weekly_cents=500_000, guaranteed_min_rides=1,
        excluded_ride_types=["SHARED"],
    )
    challenge = create_active_challenge_program(
        market["id"], challenge_ride_target=2, challenge_payout_cents=12_000,
        excluded_ride_types=["SHARED"],
    )
    enroll(guarantee["id"], driver["id"])
    challenge_enr = enroll(challenge["id"], driver["id"])

    set_clock(WEEK_MID)
    shared = complete_ride_end_to_end(driver, market["id"], ride_type="SHARED",
                                      base_fare_cents=40_000)
    standard = complete_ride_end_to_end(driver, market["id"], ride_type="STANDARD",
                                        base_fare_cents=60_000)

    settlement = validate_success(
        api.compute_settlement(
            {"driver_id": driver["id"], "program_id": guarantee["id"],
             "week_start_utc": WEEK_START},
            PAY,
        ),
        201,
    )
    assert settlement["actual_gross_cents"] == 60_000, (
        f"the SHARED ride is filtered out of the guarantee basis, got "
        f"{settlement['actual_gross_cents']}"
    )
    assert settlement["qualifying_ride_count"] == 1
    assert settlement["make_up_cents"] == 440_000

    challenge_enr = read_enrollment(challenge_enr["id"])
    assert challenge_enr["progress_count"] == 1, (
        f"the SHARED ride must not advance the challenge, got "
        f"{challenge_enr['progress_count']}"
    )


def test_forecast_approve_computes_headroom_and_supersedes_prior(api):
    """PRD §3.4: "On approval, any prior APPROVED forecast for the same program
    transitions to SUPERSEDED, the program's forecast_headroom_cents is
    recomputed, and the program's version increments by one."
    PRD §3.3: "Programs also carry a forecast_headroom_cents figure, the
    incentive budget remaining after the latest APPROVED CostForecast for that
    program; it is recomputed each time a forecast is approved."

    Design: Corner/calculations/forecast_approve_computes_headroom_and_supersedes_prior
    """
    set_clock()
    market, _driver = create_market_with_driver(market_code="GNV", budget=10_000_000)
    program = create_challenge_program(market["id"], challenge_ride_target=10,
                                       challenge_payout_cents=20_000)

    fc1 = validate_success(
        api.create_forecast(
            program["id"],
            create_forecast_payload(baseline_rides=1000, lift_bps=1000,
                                    cannibalization_bps=0),
            OPS,
        ),
        201,
    )
    program = read_program(program["id"])
    fc1 = validate_success(
        api.approve_forecast(fc1["id"],
                             {"expected_program_version": program["version"]},
                             OPS),
        200,
    )
    assert fc1["status"] == "APPROVED"
    # floor(100/10)*20000 = 200000
    assert fc1["projected_cost_cents"] == 200_000

    fc2 = validate_success(
        api.create_forecast(
            program["id"],
            create_forecast_payload(baseline_rides=1000, lift_bps=2000,
                                    cannibalization_bps=0),
            OPS,
        ),
        201,
    )
    program = read_program(program["id"])
    fc2 = validate_success(
        api.approve_forecast(fc2["id"],
                             {"expected_program_version": program["version"]},
                             OPS),
        200,
    )
    assert fc2["status"] == "APPROVED"
    assert fc2["forecast_revision"] == 2
    # floor(200/10)*20000 = 400000
    assert fc2["projected_cost_cents"] == 400_000

    # fc1 is superseded by the newer approval (PRD §3.4: "any prior APPROVED
    # forecast for the same program transitions to SUPERSEDED").
    from test_helpers import validate_paginated
    forecasts, _meta = validate_paginated(
        api.list_program_forecasts(program["id"], OPS)
    )
    statuses = {f["id"]: f["status"] for f in forecasts}
    assert statuses.get(fc1["id"]) == "SUPERSEDED", (
        f"prior APPROVED forecast must be SUPERSEDED, got "
        f"{statuses.get(fc1['id'])}"
    )

    program = read_program(program["id"])
    assert program["forecast_headroom_cents"] == 9_600_000, (
        f"10000000 - 400000 = 9600000, got {program['forecast_headroom_cents']}"
    )
