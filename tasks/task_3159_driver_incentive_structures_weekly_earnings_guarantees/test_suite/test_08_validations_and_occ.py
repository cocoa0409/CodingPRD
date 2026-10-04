"""Corner queue B: validation violations (eligibility, fraud, cross-market,
duplicate, budget, program-type), and endpoint-level OCC."""

from test_helpers import (
    ADMIN,
    FRAUD,
    OPS,
    PAY,
    WEEK_START,
    activate_program,
    complete_ride_end_to_end,
    confirm_flag,
    create_active_challenge_program,
    create_active_streak_program,
    create_challenge_program,
    create_driver,
    create_forecast_payload,
    create_guarantee_program,
    create_market,
    create_market_with_driver,
    create_streak_program,
    enroll,
    open_fraud_flag,
    rate_events_payload,
    read_driver,
    read_market,
    read_program,
    set_clock,
    setup_guarantee_scenario,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# corner: validations
# ============================================================================
def test_ineligible_driver_enrollment_rejected(api):
    """PRD §3.5: "Eligibility is next: a driver whose rate_posture is
    INELIGIBLE is refused with ERR_DRIVER_INELIGIBLE, while ELIGIBLE and
    PROBATION drivers pass."

    Design: Corner/validations/ineligible_driver_enrollment_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="HSV", budget=10_000_000)
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=1, declined=19), OPS),
        200,
    )
    assert driver["rate_posture"] == "INELIGIBLE"

    program = create_active_streak_program(market["id"])
    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_DRIVER_INELIGIBLE.value)


def test_fraud_restricted_driver_enrollment_rejected(api):
    """PRD §3.5: "The fraud gate comes first among the business rules: a driver
    whose fraud_posture is RESTRICTED is refused with ERR_FRAUD_RESTRICTED
    (HTTP 422)."
    PRD §3.9: "fraud_posture is derived: RESTRICTED when acute_score is at
    least 10; otherwise WATCH when acute_score is at least 4 or chronic_score
    is at least 4; otherwise CLEAR."

    Design: Corner/validations/fraud_restricted_driver_enrollment_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="MGM", budget=10_000_000)
    ride = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag = open_fraud_flag(driver["id"], ride["id"], severity=10,
                           signal_type="INFLATED_RIDE")
    confirm_flag(flag["id"])
    assert read_driver(driver["id"])["fraud_posture"] == "RESTRICTED"

    program = create_active_streak_program(market["id"])
    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_FRAUD_RESTRICTED.value)


def test_cross_market_enrollment_rejected(api):
    """PRD §3.5: "Referential coherence follows: the driver's home market must
    equal the program's market, with violations refused as
    ERR_CROSS_MARKET_REFERENCE."

    Design: Corner/validations/cross_market_enrollment_rejected
    """
    set_clock()
    market_a = create_market(market_code="TRI", incentive_budget_cents=1_000_000)
    market_b = create_market(market_code="KNX", incentive_budget_cents=10_000_000)
    driver = create_driver(market_a["id"], display_name="Cross Chris")
    program = create_active_streak_program(market_b["id"])

    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_CROSS_MARKET_REFERENCE.value)


def test_duplicate_active_enrollment_on_same_program_rejected(api):
    """PRD §3.5: "Finally, a driver who already holds an ACTIVE enrollment on
    the same program is refused with ERR_ENROLLMENT_DUPLICATE (HTTP 409)."

    Design: Corner/validations/duplicate_active_enrollment_on_same_program_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="CHA", budget=10_000_000)
    program = create_active_streak_program(market["id"])
    enroll(program["id"], driver["id"])

    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_ENROLLMENT_DUPLICATE.value)


def test_guarantee_activation_reservation_must_fit_budget(api):
    """PRD §3.3: "when the program is a GUARANTEE, only when the market's
    budget_available_cents is at least the program's guaranteed_weekly_cents so
    the reservation fits; ... an over-budget reservation surfaces as
    ERR_BUDGET_EXCEEDED."

    Design: Corner/validations/guarantee_activation_reservation_must_fit_budget
    """
    set_clock()
    market = create_market(market_code="AYO", incentive_budget_cents=500_000)
    program = create_guarantee_program(market["id"], guaranteed_weekly_cents=600_000,
                                       guaranteed_min_rides=1)

    response = api.activate_program(program["id"], OPS)
    validate_error(response, ApiErrorId.ERR_BUDGET_EXCEEDED.value)
    assert read_program(program["id"])["status"] == "DRAFT"
    assert read_market(market["id"])["budget_reserved_cents"] == 0


def test_settlement_compute_against_non_guarantee_program_rejected(api):
    """PRD §3.8: "The program must be a GUARANTEE program — compute against any
    other type is refused with ERR_PROGRAM_NOT_GUARANTEE (HTTP 422)."

    Design: Corner/validations/settlement_compute_against_non_guarantee_program_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="FYV", budget=10_000_000)
    program = create_active_challenge_program(market["id"])
    enroll(program["id"], driver["id"])

    response = api.compute_settlement(
        {"driver_id": driver["id"], "program_id": program["id"],
         "week_start_utc": WEEK_START},
        PAY,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_NOT_GUARANTEE.value)


def test_deactivate_driver_with_open_settlement_rejected(api):
    """PRD §3.2: "Deactivation itself is a PlatformAdmin action, permitted only
    when the driver is ACTIVE and has no GuaranteeSettlement in DRAFT or
    REOPENED."

    Design: Corner/validations/deactivate_driver_with_open_settlement_rejected
    """
    market, driver, program, enrollment = setup_guarantee_scenario(
        market_code="XNA", budget=10_000_000
    )
    settlement = validate_success(
        api.compute_settlement(
            {"driver_id": driver["id"], "program_id": program["id"],
             "week_start_utc": WEEK_START},
            PAY,
        ),
        201,
    )
    assert settlement["status"] == "DRAFT"

    response = api.deactivate_driver(driver["id"], ADMIN)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_driver(driver["id"])["account_status"] == "ACTIVE"


# ============================================================================
# corner: endpoints (OCC)
# ============================================================================
def test_forecast_approve_with_stale_program_version_rejected(api):
    """PRD §2.8: "Approving a CostForecast requires the client to supply
    expected_program_version carrying the owning IncentiveProgram's version as
    the client last observed it. A mismatch — which happens, for example, when
    a prior approval has already advanced the program's version — is rejected
    with ERR_STALE_PROGRAM_VERSION (HTTP 412)."

    Design: Corner/endpoints/forecast_approve_with_stale_program_version_rejected
    """
    set_clock()
    market, _driver = create_market_with_driver(market_code="ROK", budget=10_000_000)
    program = create_challenge_program(market["id"], challenge_ride_target=10,
                                       challenge_payout_cents=20_000)
    fc = validate_success(
        api.create_forecast(program["id"], create_forecast_payload(
            baseline_rides=1000, lift_bps=1000, cannibalization_bps=0), OPS),
        201,
    )
    program = read_program(program["id"])
    assert program["version"] >= 1

    response = api.approve_forecast(
        fc["id"], {"expected_program_version": program["version"] - 1}, OPS
    )
    validate_error(response, ApiErrorId.ERR_STALE_PROGRAM_VERSION.value)

    # Forecast remains DRAFT on a stale approval.
    from test_helpers import validate_paginated
    forecasts, _meta = validate_paginated(
        api.list_program_forecasts(program["id"], OPS)
    )
    statuses = {f["id"]: f["status"] for f in forecasts}
    assert statuses.get(fc["id"]) == "DRAFT"


def test_market_budget_update_with_stale_version_rejected(api):
    """PRD §2.8: "Updating a market's weekly incentive budget requires the
    client to supply expected_market_version carrying the market's version as
    the client last observed it. If the market's current version no longer
    matches — for example because a program activation has advanced the budget
    reservation since the client read the market — the update is rejected with
    ERR_STALE_MARKET_VERSION (HTTP 412)."
    PRD §3.1: "The update recomputes budget_available_cents, increments the
    market's version, and is refused with ERR_BUDGET_EXCEEDED when the proposed
    ceiling would fall below what is already spent plus reserved."

    Design: Corner/endpoints/market_budget_update_with_stale_version_rejected
    """
    set_clock()
    market = create_market(market_code="HHH", incentive_budget_cents=1_000_000)
    observed_version = market["version"]

    response = api.update_market(
        market["id"],
        {"incentive_budget_cents": 2_000_000,
         "expected_market_version": observed_version - 1},
        ADMIN,
    )
    validate_error(response, ApiErrorId.ERR_STALE_MARKET_VERSION.value)

    market = validate_success(
        api.update_market(
            market["id"],
            {"incentive_budget_cents": 2_000_000,
             "expected_market_version": observed_version},
            ADMIN,
        ),
        200,
    )
    assert market["incentive_budget_cents"] == 2_000_000
    assert market["version"] == observed_version + 1


def test_collusion_ring_confirm_floors_ring_members_at_watch(api):
    """PRD §3.9: "When the confirmed flag carries a non-null ring_id, every
    other driver holding an OPEN or CONFIRMED flag sharing that ring_id also
    has their posture recomputed with a WATCH floor."
    PRD §3.9: "Confirming a flag — permitted only from OPEN, and landing the
    flag in the terminal CONFIRMED state — recomputes the flagged driver's
    posture and, when the anchor ride is still COMPLETED, forces it to
    UNDER_REVIEW."

    Design: Corner/endpoints/collusion_ring_confirm_floors_ring_members_at_watch
    """
    set_clock()
    market, driver_a = create_market_with_driver(market_code="TLH", budget=10_000_000,
                                                 driver_name="Ring Ann")
    driver_b = create_driver(market["id"], display_name="Ring Bob")

    ride_a = complete_ride_end_to_end(driver_a, market["id"], base_fare_cents=5000)
    ride_b = complete_ride_end_to_end(driver_b, market["id"], base_fare_cents=5000)

    flag_a = open_fraud_flag(driver_a["id"], ride_a["id"], severity=10,
                             signal_type="COLLUSION", ring_id="R1")
    open_fraud_flag(driver_b["id"], ride_b["id"], severity=2,
                    signal_type="COLLUSION", ring_id="R1")

    confirm_flag(flag_a["id"])

    driver_a = read_driver(driver_a["id"])
    assert driver_a["fraud_posture"] == "RESTRICTED", (
        f"acute 10 >= 10 forces RESTRICTED, got {driver_a['fraud_posture']}"
    )

    driver_b = read_driver(driver_b["id"])
    assert driver_b["fraud_posture"] == "WATCH", (
        f"ring membership floors at WATCH even with an OPEN severity-2 flag, "
        f"got {driver_b['fraud_posture']}"
    )

    ride_a = validate_success(api.get_ride(ride_a["id"], FRAUD), 200)
    assert ride_a["status"] == "UNDER_REVIEW"


def test_supply_shortfall_recommended_bonus_uses_median_fare(api):
    """PRD §3.11: "Creation computes a recommended_bonus_cents suggestion: the
    market's median base_fare_cents over COMPLETED rides in the cell across the
    prior four weeks (zero when no history exists) is multiplied by
    severity_bps and divided by 10000, with the result rounded up to the next
    integer cent."

    Design: Corner/endpoints/supply_shortfall_recommended_bonus_uses_median_fare
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="PBI", budget=1_000_000,
                                               driver_name="Median Mel")
    for fare in (10_000, 20_000, 30_000):
        complete_ride_end_to_end(driver, market["id"], base_fare_cents=fare)

    shortfall = validate_success(
        api.create_supply_shortfall(
            {"market_id": market["id"], "geo_cell_id": "cellA",
             "hour_bucket": 17, "severity_bps": 5000},
            OPS,
        ),
        201,
    )
    # median of [10000, 20000, 30000] is 20000; 5000 bps doubles... half.
    assert shortfall["recommended_bonus_cents"] == 10_000, (
        f"ceil(5000*20000/10000) = 10000, got "
        f"{shortfall['recommended_bonus_cents']}"
    )
    assert shortfall["status"] == "OPEN"
