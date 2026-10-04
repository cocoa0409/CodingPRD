"""Non-linear state machines: cyclic appeals, parallel postures, settlement
reopen cycles (difficulty queue A)."""

from test_helpers import (
    ADMIN,
    FRAUD,
    OPS,
    PAY,
    WEEK_MID,
    activate_program,
    complete_ride_end_to_end,
    compute_settlement,
    confirm_flag,
    create_active_zone_program,
    create_market_with_driver,
    create_offered_ride,
    create_streak_program,
    enroll,
    file_eligibility_appeal,
    finalize_settlement,
    make_driver_headers,
    open_fraud_flag,
    rate_events_payload,
    read_appeal,
    read_driver,
    read_enrollment,
    read_ride,
    read_settlement,
    set_clock,
    setup_appeal_under_review,
    setup_guarantee_with_rides,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# non_linear_state_machine
# ============================================================================
def test_appeal_cycles_two_info_rounds_then_escalates(api):
    """PRD §3.10: "Requesting more information moves UNDER_REVIEW to MORE_INFO,
    and is available only while round_count is below 2."
    PRD §3.10: "The driver responds by providing the requested information,
    which returns the appeal to UNDER_REVIEW and increments round_count."
    PRD §3.10: "When both information rounds have been consumed — round_count
    exactly 2 — the PaymentsOfficer may escalate, moving UNDER_REVIEW to
    ESCALATED."

    Design: Difficulty/non_linear_state_machine/appeal_cyclic_info_rounds_then_escalate
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="OKC")
    appeal = setup_appeal_under_review(driver)

    for _ in range(2):
        appeal = validate_success(api.request_appeal_info(appeal["id"], PAY), 200)
        assert appeal["status"] == "MORE_INFO"
        appeal = validate_success(
            api.provide_appeal_info(appeal["id"], make_driver_headers(driver["id"])),
            200,
        )
        assert appeal["status"] == "UNDER_REVIEW"

    assert appeal["round_count"] == 2, (
        f"two MORE_INFO -> UNDER_REVIEW cycles must yield round_count 2, got "
        f"{appeal['round_count']}"
    )
    appeal = validate_success(api.escalate_appeal(appeal["id"], PAY), 200)
    assert appeal["status"] == "ESCALATED"


def test_appeal_third_info_round_rejected_rounds_exhausted(api):
    """PRD §3.10: "Requesting more information moves UNDER_REVIEW to MORE_INFO,
    and is available only while round_count is below 2 — requesting a third
    round is refused with ERR_APPEAL_ROUNDS_EXHAUSTED (HTTP 422)."

    Design: Difficulty/non_linear_state_machine/appeal_cyclic_info_rounds_then_escalate
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="OKD")
    appeal = setup_appeal_under_review(driver)

    for _ in range(2):
        appeal = validate_success(api.request_appeal_info(appeal["id"], PAY), 200)
        appeal = validate_success(
            api.provide_appeal_info(appeal["id"], make_driver_headers(driver["id"])),
            200,
        )
    assert appeal["round_count"] == 2

    response = api.request_appeal_info(appeal["id"], PAY)
    validate_error(response, ApiErrorId.ERR_APPEAL_ROUNDS_EXHAUSTED.value)
    appeal = read_appeal(appeal["id"])
    assert appeal["status"] == "UNDER_REVIEW"


def test_driver_rate_posture_moves_ineligible_without_touching_fraud(api):
    """PRD §2.10: "Every Driver carries two independent posture dimensions, and
    nothing about one implies anything about the other."
    PRD §3.2: "if acceptance_rate_bps is at least 9000 and
    cancellation_rate_bps is at most 1000, the posture is ELIGIBLE. Failing
    that, if acceptance_rate_bps is at least 7500 and cancellation_rate_bps is
    at most 2000, the posture is PROBATION. Anything else is INELIGIBLE."

    Design: Difficulty/non_linear_state_machine/driver_parallel_rate_and_fraud_postures_move_independently
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="AMA")

    # 3 accepts / 17 declines over 20 offers -> acceptance 1500 bps.
    response = api.record_rate_events(
        driver["id"], rate_events_payload(accepted=3, declined=17), OPS
    )
    driver = validate_success(response, 200)
    assert driver["offers_total"] == 20
    assert driver["acceptance_rate_bps"] == 1500, (
        f"floor(10000*3/20) = 1500, got {driver['acceptance_rate_bps']}"
    )
    assert driver["rate_posture"] == "INELIGIBLE"
    assert driver["fraud_posture"] == "CLEAR", (
        f"rate events must not move fraud_posture, got {driver['fraud_posture']}"
    )

    # Confirm a severity-4 flag: fraud dimension moves, rate dimension stays.
    ride = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag = open_fraud_flag(driver["id"], ride["id"], severity=4,
                           signal_type="LOCATION_SPOOF")
    confirm_flag(flag["id"])

    driver = read_driver(driver["id"])
    assert driver["fraud_posture"] == "WATCH", (
        f"acute 4 >= WATCH threshold 4 forces WATCH, got {driver['fraud_posture']}"
    )
    assert driver["rate_posture"] == "INELIGIBLE", (
        f"fraud confirm must not move rate_posture, got {driver['rate_posture']}"
    )


def test_driver_fraud_posture_watch_requires_watch_threshold(api):
    """PRD §3.9: "fraud_posture is derived: RESTRICTED when acute_score is at
    least 10; otherwise WATCH when acute_score is at least 4 or chronic_score
    is at least 4; otherwise CLEAR."

    Design: Difficulty/non_linear_state_machine/driver_parallel_rate_and_fraud_postures_move_independently
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="AM2")
    ride = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)

    # severity 3 < WATCH_MIN 4: posture stays CLEAR.
    flag = open_fraud_flag(driver["id"], ride["id"], severity=3,
                           signal_type="LOCATION_SPOOF")
    confirm_flag(flag["id"])
    driver = read_driver(driver["id"])
    assert driver["fraud_posture"] == "CLEAR", (
        f"acute 3 < 4 keeps CLEAR, got {driver['fraud_posture']}"
    )

    # A second severity-3 flag pushes acute to 6 >= 4: posture moves to WATCH.
    ride2 = complete_ride_end_to_end(driver, market["id"], base_fare_cents=5000)
    flag2 = open_fraud_flag(driver["id"], ride2["id"], severity=3,
                            signal_type="LOCATION_SPOOF")
    confirm_flag(flag2["id"])
    driver = read_driver(driver["id"])
    assert driver["fraud_posture"] == "WATCH"
    assert driver["rate_posture"] == "ELIGIBLE", (
        f"fraud confirms never move rate_posture, got {driver['rate_posture']}"
    )


def test_settlement_reopened_by_flag_review_and_refinalized(api):
    """PRD §3.9: "Flagging a COMPLETED ride for review moves it to
    UNDER_REVIEW, which excludes it from PROVISIONAL guarantee basis and forces
    any FINALIZED settlement covering that driver and week into REOPENED,
    drafting statement adjustments."
    PRD §3.9: "Clearing the review returns the ride to COMPLETED and
    re-includes it in the FINAL basis."

    Design: Difficulty/non_linear_state_machine/settlement_finalize_reopen_refinalize_cycle
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="TUS", guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    ride1 = rides[0]
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])
    assert settlement["status"] == "FINALIZED"
    assert settlement["make_up_cents"] == 400_000

    # Cascade: flag-review on the week ride reopens the FINALIZED settlement.
    validate_success(api.flag_ride_review(ride1["id"], FRAUD), 200)
    settlement = read_settlement(settlement["id"])
    assert settlement["status"] == "REOPENED", (
        f"flag-review must reopen the FINALIZED settlement, got "
        f"{settlement['status']}"
    )

    # Clear the review and re-finalize.
    validate_success(api.clear_ride_review(ride1["id"], FRAUD), 200)
    settlement = validate_success(api.finalize_settlement(settlement["id"], PAY), 200)
    assert settlement["status"] == "FINALIZED"
    assert settlement["basis_variant"] == "FINAL"
    assert settlement["make_up_cents"] == 400_000, (
        f"500000 - 100000 = 400000 again after re-finalize, got "
        f"{settlement['make_up_cents']}"
    )


def test_settlement_reopen_then_finalize_keeps_make_up(api):
    """PRD §3.8: "reopening moves FINALIZED to REOPENED, restoring PROVISIONAL
    semantics until re-finalized, and a re-finalization after reopening drafts
    an adjustment on the week statement for the delta."
    PRD §3.8: "Finalization converts the settlement to the FINAL variant. It is
    permitted from DRAFT or REOPENED."

    Design: Difficulty/non_linear_state_machine/settlement_finalize_reopen_refinalize_cycle
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="TU3", guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])

    settlement = validate_success(api.reopen_settlement(settlement["id"], PAY), 200)
    assert settlement["status"] == "REOPENED"

    settlement = validate_success(api.finalize_settlement(settlement["id"], PAY), 200)
    assert settlement["status"] == "FINALIZED"
    assert settlement["make_up_cents"] == 400_000
