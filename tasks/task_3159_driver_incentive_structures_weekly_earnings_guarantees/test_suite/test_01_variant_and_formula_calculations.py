"""Dual-variant calculations and combinatorial formulas (difficulty queue A)."""

from test_helpers import (
    ADMIN,
    FRAUD,
    OPS,
    PAY,
    WEEK_MID,
    WEEK_START,
    activate_program,
    complete_ride_end_to_end,
    compute_settlement,
    confirm_flag,
    create_active_zone_program,
    create_forecast_payload,
    create_guarantee_program,
    create_market_with_driver,
    create_offered_ride,
    create_streak_program,
    enroll,
    make_driver_headers,
    read_driver,
    read_enrollment,
    read_market,
    read_ride,
    read_settlement,
    set_clock,
    setup_guarantee_with_rides,
    validate_success,
)


# ============================================================================
# dual_variant_calc
# ============================================================================
def test_guarantee_provisional_excludes_under_review_ride(api):
    """PRD §2.11: "The PROVISIONAL variant applies when a settlement is first
    computed in DRAFT: it excludes rides currently in UNDER_REVIEW from both the
    earnings basis and the qualifying ride count."
    PRD §3.8: "`make_up_cents` is zero when `qualifying_ride_count` is below the
    program's `guaranteed_min_rides` and otherwise the larger of zero and
    `promised_cents` minus `actual_gross_cents`."

    Design: Difficulty/dual_variant_calc/guarantee_make_up_provisional_excludes_under_review_final_includes
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="SFO", guaranteed_min_rides=2,
        ride_fares_cents=(100_000, 100_000),
    )
    ride1, ride2 = rides

    # Flag ride1 BEFORE compute so the DRAFT excludes it.
    ride1 = validate_success(api.flag_ride_review(ride1["id"], FRAUD), 200)

    settlement = validate_success(
        api.compute_settlement(
            {"driver_id": driver["id"], "program_id": program["id"],
             "week_start_utc": WEEK_START},
            PAY,
        ),
        201,
    )
    assert settlement["basis_variant"] == "PROVISIONAL"
    assert settlement["qualifying_ride_count"] == 1, (
        f"UNDER_REVIEW ride must be excluded from the count, got "
        f"{settlement['qualifying_ride_count']}"
    )
    assert settlement["actual_gross_cents"] == 100_000
    assert settlement["make_up_cents"] == 0, (
        f"count 1 below guaranteed_min_rides 2 forces make_up 0, got "
        f"{settlement['make_up_cents']}"
    )


def test_guarantee_final_includes_ride_cleared_from_review(api):
    """PRD §2.11: "The FINAL variant applies at finalize time: it re-includes
    rides whose review resolved back to COMPLETED and permanently excludes
    VOIDED rides."
    PRD §2.11: "The same underlying ride set can therefore produce two different
    make_up_cents figures under the two variants."

    Design: Difficulty/dual_variant_calc/guarantee_make_up_provisional_excludes_under_review_final_includes
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="SFO", guaranteed_min_rides=2,
        ride_fares_cents=(100_000, 100_000),
    )
    ride1, ride2 = rides

    ride1 = validate_success(api.flag_ride_review(ride1["id"], FRAUD), 200)
    settlement = validate_success(
        api.compute_settlement(
            {"driver_id": driver["id"], "program_id": program["id"],
             "week_start_utc": WEEK_START},
            PAY,
        ),
        201,
    )
    assert settlement["make_up_cents"] == 0

    # Resolve the review back to COMPLETED, then finalize under FINAL.
    validate_success(api.clear_ride_review(ride1["id"], FRAUD), 200)
    settlement = validate_success(api.finalize_settlement(settlement["id"], PAY), 200)

    assert settlement["basis_variant"] == "FINAL"
    assert settlement["qualifying_ride_count"] == 2
    assert settlement["actual_gross_cents"] == 200_000
    assert settlement["make_up_cents"] == 300_000, (
        f"FINAL must include the cleared ride: 500000 - 200000 = 300000, got "
        f"{settlement['make_up_cents']}"
    )


def test_fraud_acute_score_is_flat_sum_of_confirmed_severities(api):
    """PRD §3.9: "The acute_score is the flat sum of severity across the
    driver's CONFIRMED flags — no decay."
    PRD §3.9: "fraud_posture is derived: RESTRICTED when acute_score is at
    least 10; otherwise WATCH when acute_score is at least 4 or chronic_score
    is at least 4; otherwise CLEAR."

    Design: Difficulty/dual_variant_calc/fraud_score_acute_flat_vs_chronic_decayed
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="ATX")
    ride1 = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag1 = validate_success(
        api.create_fraud_flag(
            {"driver_id": driver["id"], "ride_id": ride1["id"],
             "signal_type": "INFLATED_RIDE", "severity": 6},
            FRAUD,
        ),
        201,
    )
    confirm_flag(flag1["id"])

    # Advance past one full 4-week decay bucket and confirm a second flag.
    set_clock("2026-10-06T00:00:00Z")
    ride2 = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag2 = validate_success(
        api.create_fraud_flag(
            {"driver_id": driver["id"], "ride_id": ride2["id"],
             "signal_type": "COLLUSION", "severity": 6},
            FRAUD,
        ),
        201,
    )
    flag2 = confirm_flag(flag2["id"])

    assert flag2["acute_score"] == 12, (
        f"acute is the flat sum 6+6=12, got {flag2['acute_score']}"
    )
    driver_now = read_driver(driver["id"])
    assert driver_now["fraud_posture"] == "RESTRICTED", (
        f"acute 12 >= 10 forces RESTRICTED, got {driver_now['fraud_posture']}"
    )


def test_fraud_chronic_score_decays_per_four_week_bucket(api):
    """PRD §3.9: "each confirmed flag's severity halves per full four-week
    bucket of age."
    PRD §3.9: "otherwise WATCH when acute_score is at least 4 or chronic_score
    is at least 4; otherwise CLEAR."

    Design: Difficulty/dual_variant_calc/fraud_score_acute_flat_vs_chronic_decayed
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="ATX")
    ride1 = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag1 = validate_success(
        api.create_fraud_flag(
            {"driver_id": driver["id"], "ride_id": ride1["id"],
             "signal_type": "INFLATED_RIDE", "severity": 6},
            FRAUD,
        ),
        201,
    )
    confirm_flag(flag1["id"])

    set_clock("2026-10-06T00:00:00Z")  # > one full 4-week bucket later
    ride2 = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag2 = validate_success(
        api.create_fraud_flag(
            {"driver_id": driver["id"], "ride_id": ride2["id"],
             "signal_type": "COLLUSION", "severity": 6},
            FRAUD,
        ),
        201,
    )
    flag2 = confirm_flag(flag2["id"])

    assert flag2["chronic_score"] == 9, (
        f"chronic halves the aged flag: floor(600/2)/100 = 3 plus fresh 6 = 9, "
        f"got {flag2['chronic_score']}"
    )
    # Variants disagree on the same flag set.
    assert flag2["acute_score"] == 12
    assert flag2["acute_score"] != flag2["chronic_score"]


# ============================================================================
# combinatorial_formula
# ============================================================================
def test_streak_payout_combines_zone_boost(api):
    """PRD §3.7: "if an ACTIVE BONUS_ZONE enrollment of the same driver covers
    the ride's cell, a zone boost is added equal to the floor of the base
    payout times zone_multiplier_bps minus 10000, divided by 10000."
    PRD §3.7: "the payout is the smaller of the raw total and the market's
    budget_available_cents at that moment."

    Design: Difficulty/combinatorial_formula/streak_payout_zone_boost_and_budget_min
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="PDX", budget=10_000_000)
    streak = create_streak_program(market["id"], streak_length=2,
                                   streak_payout_cents=5000)
    activate_program(streak["id"])
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    streak_enr = enroll(streak["id"], driver["id"])
    zone_enr = enroll(zone["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=20_000)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=20_000)

    streak_enr = read_enrollment(streak_enr["id"])
    assert streak_enr["status"] == "COMPLETED"
    assert streak_enr["payout_cents"] == 7500, (
        f"5000 base + floor(5000*5000/10000)=2500 boost = 7500, got "
        f"{streak_enr['payout_cents']}"
    )


def test_streak_zone_boost_accumulates_zone_payout_and_spend(api):
    """PRD §3.6: "BONUS_ZONE enrollments whose geo_cell_id matches the ride's
    pickup cell accrue the per-ride zone bonus."
    PRD §3.6: "Streak and challenge completions move the enrollment to
    COMPLETED and add the payout to the market's budget_spent_cents; zone
    bonuses accrue ride-by-ride and each accrual increments budget_spent_cents
    individually."

    Design: Difficulty/combinatorial_formula/streak_payout_zone_boost_and_budget_min
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="PDX", budget=10_000_000)
    streak = create_streak_program(market["id"], streak_length=2,
                                   streak_payout_cents=5000)
    activate_program(streak["id"])
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    streak_enr = enroll(streak["id"], driver["id"])
    zone_enr = enroll(zone["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=20_000)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=20_000)

    zone_enr = read_enrollment(zone_enr["id"])
    assert zone_enr["payout_cents"] == 20_000, (
        f"two rides x floor(20000*5000/10000)=10000 each = 20000, got "
        f"{zone_enr['payout_cents']}"
    )
    market_now = read_market(market["id"])
    assert market_now["budget_spent_cents"] == 27_500, (
        f"7500 streak payout + 20000 zone bonus = 27500, got "
        f"{market_now['budget_spent_cents']}"
    )


def test_zone_bonus_per_ride_floor_beats_sum_then_round(api):
    """PRD §2.6: "three rides of 333 cents each under a 15000-basis-point
    multiplier yield 3 × floor(333 × 5000 / 10000) = 3 × 166 = 498 cents, not
    floor(999 × 5000 / 10000) = 499."
    PRD §3.7: "each ride's bonus is floored to integer cents before
    accumulation, and computing the floor over summed fares is forbidden."

    Design: Difficulty/combinatorial_formula/zone_bonus_per_ride_floor_beats_sum_then_round
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="BOI", budget=10_000_000)
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    zone_enr = enroll(zone["id"], driver["id"])

    set_clock(WEEK_MID)
    for _ in range(3):
        complete_ride_end_to_end(driver, market["id"], base_fare_cents=333)

    zone_enr = read_enrollment(zone_enr["id"])
    assert zone_enr["payout_cents"] == 498, (
        f"per-ride floor: 3 x 166 = 498 (sum-then-round would give 499), got "
        f"{zone_enr['payout_cents']}"
    )
    market_now = read_market(market["id"])
    assert market_now["budget_spent_cents"] == 498


def test_zone_bonus_per_ride_floor_second_reading(api):
    """PRD §2.6: "For per-ride bonus accumulation (zone bonuses), the floor is
    applied to each ride's bonus first and the integer results are accumulated.
    Computing the floor over the sum of fares is forbidden."

    Design: Difficulty/combinatorial_formula/zone_bonus_per_ride_floor_beats_sum_then_round
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="BO2", budget=10_000_000)
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    zone_enr = enroll(zone["id"], driver["id"])

    set_clock(WEEK_MID)
    # Two 333-cent rides: 2 * 166 = 332 (sum-then-round would give
    # floor(666*5000/10000) = 333).
    for _ in range(2):
        complete_ride_end_to_end(driver, market["id"], base_fare_cents=333)

    zone_enr = read_enrollment(zone_enr["id"])
    assert zone_enr["payout_cents"] == 332, (
        f"per-ride floor: 2 x 166 = 332 (sum-then-round would give 333), got "
        f"{zone_enr['payout_cents']}"
    )


def test_cost_forecast_pinned_evaluation_order_streak(api):
    """PRD §3.4: "First, projected_incremental_rides is the floor of
    baseline_rides times lift_bps divided by 10000. Second,
    projected_cannibalized_rides is the floor of projected_incremental_rides
    times cannibalization_bps divided by 10000. Third, the net new ride count
    is projected_incremental_rides minus projected_cannibalized_rides. Fourth,
    projected_cost_cents depends on the program type: for a STREAK program it
    is the floor of net new rides divided by the larger of 1 and streak_length,
    multiplied by streak_payout_cents."

    Design: Difficulty/combinatorial_formula/cost_forecast_pinned_evaluation_order
    """
    set_clock()
    market, _driver = create_market_with_driver(market_code="TUL", budget=10_000_000)
    program = create_streak_program(market["id"], streak_length=3,
                                    streak_payout_cents=5000)

    forecast = validate_success(
        api.create_forecast(
            program["id"],
            create_forecast_payload(baseline_rides=1000, lift_bps=2000,
                                    cannibalization_bps=2500),
            OPS,
        ),
        201,
    )

    assert forecast["projected_incremental_rides"] == 200
    assert forecast["projected_cannibalized_rides"] == 50
    assert forecast["projected_cost_cents"] == 250_000, (
        f"floor(150/3)*5000 = 250000, got {forecast['projected_cost_cents']}"
    )
    assert forecast["forecast_revision"] == 1
    assert forecast["status"] == "DRAFT"


def test_cost_forecast_revision_monotonic_per_program(api):
    """PRD §3.4: "stores the forecast in DRAFT with a forecast_revision number
    that is monotonic per program starting at 1."

    Design: Difficulty/combinatorial_formula/cost_forecast_pinned_evaluation_order
    """
    set_clock()
    market, _driver = create_market_with_driver(market_code="TU2", budget=10_000_000)
    program = create_streak_program(market["id"], streak_length=3,
                                    streak_payout_cents=5000)

    first = validate_success(
        api.create_forecast(program["id"], create_forecast_payload(), OPS), 201
    )
    second = validate_success(
        api.create_forecast(program["id"], create_forecast_payload(), OPS), 201
    )
    assert first["forecast_revision"] == 1
    assert second["forecast_revision"] == 2, (
        f"revision must be monotonic per program, got {second['forecast_revision']}"
    )
