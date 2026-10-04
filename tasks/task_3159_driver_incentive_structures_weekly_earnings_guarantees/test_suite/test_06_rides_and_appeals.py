"""Corner queue B: ride/state-machine behaviours, appeals, lifecycle cascades."""

from test_helpers import (
    ADMIN,
    FRAUD,
    OPS,
    PAY,
    WEEK_MID,
    accept_ride,
    cancel_ride,
    complete_ride_end_to_end,
    compute_settlement,
    create_active_guarantee_program,
    create_active_streak_program,
    create_active_zone_program,
    create_driver,
    create_market,
    create_market_with_driver,
    create_offered_ride,
    create_streak_program,
    create_supply_shortfall,
    enroll,
    file_statement_appeal,
    finalize_settlement,
    make_driver_headers,
    pay_settlement,
    read_appeal,
    read_driver,
    read_enrollment,
    read_market,
    read_program,
    read_ride,
    read_settlement,
    read_statement,
    set_clock,
    setup_appeal_under_review,
    setup_guarantee_with_rides,
    setup_published_statement,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# corner: state_machines
# ============================================================================
def test_ride_decline_latches_streak_broken_and_zeroes_progress(api):
    """PRD §3.6: "A decline does two things beyond the rate fold: it latches
    streak_broken true and zeroes progress_count on every ACTIVE STREAK
    enrollment the driver holds."

    Design: Corner/state_machines/ride_decline_latches_streak_broken_and_zeroes_progress
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="GRB", budget=10_000_000)
    program = create_active_streak_program(market["id"], streak_length=3,
                                           streak_payout_cents=5000)
    enrollment = enroll(program["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    assert read_enrollment(enrollment["id"])["progress_count"] == 1

    ride2 = create_offered_ride(driver, market["id"], base_fare_cents=8000)
    ride2 = validate_success(
        api.decline_ride(ride2["id"], make_driver_headers(driver["id"])), 200
    )
    assert ride2["status"] == "DECLINED"

    enrollment = read_enrollment(enrollment["id"])
    assert enrollment["streak_broken"] is True
    assert enrollment["progress_count"] == 0
    assert enrollment["status"] == "ACTIVE", (
        "a broken streak does not cancel the enrollment"
    )


def test_rider_cancel_preserves_streak_and_cancellation_rate(api):
    """PRD §3.6: "A driver-cancel increments cancelled_total, recomputes the
    rolling rates, and breaks any open streak runs exactly as a decline does; a
    rider-cancel has no rate impact and leaves streaks untouched."

    Design: Corner/state_machines/rider_cancel_preserves_streak_and_cancellation_rate
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="AUS", budget=10_000_000)
    program = create_active_streak_program(market["id"], streak_length=3,
                                           streak_payout_cents=5000)
    enrollment = enroll(program["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    assert read_enrollment(enrollment["id"])["progress_count"] == 1

    ride2 = create_offered_ride(driver, market["id"], base_fare_cents=8000)
    accept_ride(driver, ride2["id"])
    ride2 = validate_success(
        api.cancel_ride(ride2["id"], {"cancelled_by": "RIDER"},
                        make_driver_headers(driver["id"])),
        200,
    )
    assert ride2["status"] == "RIDER_CANCELLED"

    enrollment = read_enrollment(enrollment["id"])
    assert enrollment["streak_broken"] is False
    assert enrollment["progress_count"] == 1

    driver = read_driver(driver["id"])
    assert driver["cancelled_total"] == 0


def test_complete_terminal_ride_rejected(api):
    """PRD §3.6: "acting on a ride that has already reached a terminal state
    (COMPLETED, DRIVER_CANCELLED, RIDER_CANCELLED, DECLINED, or VOIDED) when a
    live state is required is refused with ERR_RIDE_NOT_TERMINAL-style
    semantics under ERR_RIDE_ALREADY_TERMINAL — both are HTTP 409."

    Design: Corner/state_machines/complete_terminal_ride_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="CRW")
    ride = complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    assert ride["status"] == "COMPLETED"

    response = api.complete_ride(ride["id"], make_driver_headers(driver["id"]))
    validate_error(response, ApiErrorId.ERR_RIDE_ALREADY_TERMINAL.value)
    assert read_ride(ride["id"])["status"] == "COMPLETED"


def test_retire_program_with_active_enrollment_rejected(api):
    """PRD §3.3: "Retirement moves a program from DRAFT, ACTIVE, or PAUSED to
    RETIRED and is permitted only when no enrollment on the program remains
    ACTIVE."

    Design: Corner/state_machines/retire_program_with_active_enrollment_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="CHS", budget=10_000_000)
    program = create_active_streak_program(market["id"], streak_length=2,
                                           streak_payout_cents=5000)
    enroll(program["id"], driver["id"])

    response = api.retire_program(program["id"], OPS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert read_program(program["id"])["status"] == "ACTIVE"


def test_market_close_cascades_programs_retired_and_shortfalls_expired(api):
    """PRD §3.1: "The close cascade retires every remaining program and
    expires every OPEN SupplyShortfall in the market."

    Design: Corner/state_machines/market_close_cascades_programs_retired_and_shortfalls_expired
    """
    set_clock()
    market = create_market(market_code="SAV", incentive_budget_cents=1_000_000)
    program = create_streak_program(market["id"])  # DRAFT
    shortfall = create_supply_shortfall(market["id"], geo_cell_id="cellA",
                                        hour_bucket=40, severity_bps=2500)
    assert shortfall["status"] == "OPEN"

    market = validate_success(api.close_market(market["id"], ADMIN), 200)
    assert market["status"] == "CLOSED"
    assert read_program(program["id"])["status"] == "RETIRED"
    reloaded = validate_success(
        api.get_supply_shortfall(shortfall["id"], OPS), 200
    )
    assert reloaded["status"] == "EXPIRED"


def test_direct_enrollment_cancel_releases_zone_capacity_slot(api):
    """PRD §3.5: "when the cancelled enrollment belongs to a BONUS_ZONE program
    with a capacity, the released slot returns to the program's headroom."
    PRD §3.5: "an ACTIVE enrollment may be moved to CANCELLED — by the driver
    themselves, by IncentiveOps, or by the system."

    Design: Corner/state_machines/direct_enrollment_cancel_releases_zone_capacity_slot
    """
    set_clock()
    market = create_market(market_code="ALE", incentive_budget_cents=1_000_000)
    driver1 = create_driver(market["id"], display_name="Slot Sal")
    driver2 = create_driver(market["id"], display_name="Slot Sue")
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=1)
    enr1 = enroll(zone["id"], driver1["id"])

    enr1 = validate_success(api.cancel_enrollment(enr1["id"], OPS), 200)
    assert enr1["status"] == "CANCELLED"

    enr2 = validate_success(
        api.enroll_driver(zone["id"], {"driver_id": driver2["id"]}, OPS), 201
    )
    assert enr2["status"] == "ACTIVE"


def test_exclusive_program_suppresses_stackable_streak_payout(api):
    """PRD §3.7: "if the same ride also advanced an ACTIVE enrollment in an
    EXCLUSIVE-class program, the STACKABLE streak payout is suppressed to zero
    — EXCLUSIVE wins."
    PRD §3.7: "A CHALLENGE pays its full challenge_payout_cents in one shot
    when the target is reached, subject to the same EXCLUSIVE suppression when
    the deciding ride also advanced an EXCLUSIVE enrollment."

    Design: Corner/state_machines/exclusive_program_suppresses_stackable_streak_payout
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="MSY", budget=10_000_000)
    streak = create_active_streak_program(market["id"], streak_length=2,
                                          streak_payout_cents=5000)
    from test_helpers import create_challenge_program_payload
    challenge = validate_success(
        api.create_program(
            create_challenge_program_payload(
                market["id"], challenge_ride_target=2,
                challenge_payout_cents=12_000, stacking_class="EXCLUSIVE",
            ),
            OPS,
        ),
        201,
    )
    challenge = validate_success(api.activate_program(challenge["id"], OPS), 200)

    streak_enr = enroll(streak["id"], driver["id"])
    challenge_enr = enroll(challenge["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)

    challenge_enr = read_enrollment(challenge_enr["id"])
    assert challenge_enr["status"] == "COMPLETED"
    assert challenge_enr["payout_cents"] == 12_000

    streak_enr = read_enrollment(streak_enr["id"])
    assert streak_enr["status"] == "COMPLETED"
    assert streak_enr["payout_cents"] == 0, (
        f"STACKABLE payout must be suppressed to 0 when EXCLUSIVE wins, got "
        f"{streak_enr['payout_cents']}"
    )

    market = read_market(market["id"])
    assert market["budget_spent_cents"] == 12_000


def test_appeal_withdraw_returns_disputed_statement_to_published(api):
    """PRD §3.10: "withdrawing a STATEMENT appeal whose statement is DISPUTED
    returns the statement to PUBLISHED with no monetary change."

    Design: Corner/state_machines/appeal_withdraw_returns_disputed_statement_to_published
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        setup_published_statement(market_code="JAN", guaranteed_min_rides=1,
                                  ride_fares_cents=(100_000,), tips_cents=0)
    )
    appeal = file_statement_appeal(driver, statement["id"],
                                   reason="changed my mind")
    assert read_statement(statement["id"])["status"] == "DISPUTED"

    appeal = validate_success(
        api.withdraw_appeal(appeal["id"], make_driver_headers(driver["id"])), 200
    )
    assert appeal["status"] == "WITHDRAWN"

    statement = read_statement(statement["id"])
    assert statement["status"] == "PUBLISHED"
    assert statement["adjustments_cents"] == 0


def test_resolve_overturned_statement_appeal_without_adjustment_rejected(api):
    """PRD §3.10: "Overturning a STATEMENT appeal requires a non-zero
    adjustment_cents to be supplied — its absence is refused with
    ERR_APPEAL_ADJUSTMENT_REQUIRED (HTTP 400)."

    Design: Corner/state_machines/resolve_overturned_statement_appeal_without_adjustment_rejected
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        setup_published_statement(market_code="BTR", guaranteed_min_rides=1,
                                  ride_fares_cents=(100_000,), tips_cents=0)
    )
    appeal = file_statement_appeal(driver, statement["id"], reason="wrong total")
    validate_success(api.start_appeal_review(appeal["id"], PAY), 200)

    response = api.resolve_appeal(appeal["id"], {"outcome": "OVERTURNED"}, PAY)
    validate_error(response, ApiErrorId.ERR_APPEAL_ADJUSTMENT_REQUIRED.value)

    appeal = read_appeal(appeal["id"])
    assert appeal["status"] == "UNDER_REVIEW"
    assert read_statement(statement["id"])["status"] == "DISPUTED"


def test_escalate_before_both_info_rounds_rejected(api):
    """PRD §3.10: "When both information rounds have been consumed —
    round_count exactly 2 — the PaymentsOfficer may escalate, moving
    UNDER_REVIEW to ESCALATED; escalating earlier is refused with
    ERR_APPEAL_NOT_ESCALATABLE."

    Design: Corner/state_machines/escalate_before_both_info_rounds_rejected
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="LCH")
    appeal = setup_appeal_under_review(driver)
    assert appeal["round_count"] == 0

    response = api.escalate_appeal(appeal["id"], PAY)
    validate_error(response, ApiErrorId.ERR_APPEAL_NOT_ESCALATABLE.value)

    appeal = read_appeal(appeal["id"])
    assert appeal["status"] == "UNDER_REVIEW"
