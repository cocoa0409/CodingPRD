"""Transitive cascades and validation-priority pairs (difficulty queue A)."""

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
    create_driver,
    create_guarantee_program,
    create_market,
    create_market_with_driver,
    create_streak_program,
    enroll,
    finalize_settlement,
    open_fraud_flag,
    rate_events_payload,
    read_driver,
    read_enrollment,
    read_market,
    read_program,
    read_ride,
    read_settlement,
    set_clock,
    setup_guarantee_with_rides,
    validate_error,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# transitive_cascade
# ============================================================================
def test_fraud_confirm_cascades_ride_review_settlement_reopen(api):
    """PRD §3.9: "Confirming a flag — permitted only from OPEN, and landing the
    flag in the terminal CONFIRMED state — recomputes the flagged driver's
    posture and, when the anchor ride is still COMPLETED, forces it to
    UNDER_REVIEW."
    PRD §3.9: "Flagging a COMPLETED ride for review moves it to UNDER_REVIEW,
    which excludes it from PROVISIONAL guarantee basis and forces any FINALIZED
    settlement covering that driver and week into REOPENED."

    Design: Difficulty/transitive_cascade/fraud_confirm_cascades_ride_review_settlement_reopen_statement_draft
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="LIT", guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    ride1 = rides[0]
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])
    flag = open_fraud_flag(driver["id"], ride1["id"], severity=5,
                           signal_type="INFLATED_RIDE")

    flag = confirm_flag(flag["id"])
    assert flag["status"] == "CONFIRMED"

    ride1 = read_ride(ride1["id"])
    assert ride1["status"] == "UNDER_REVIEW", (
        f"confirm must force the anchor ride into UNDER_REVIEW, got "
        f"{ride1['status']}"
    )
    settlement = read_settlement(settlement["id"])
    assert settlement["status"] == "REOPENED", (
        f"the ride transition must reopen the FINALIZED settlement, got "
        f"{settlement['status']}"
    )


def test_fraud_confirm_blocks_settlement_finalize_while_ride_under_review(api):
    """PRD §3.8: "It is permitted from DRAFT or REOPENED, requires every ride
    for the driver in the settled week to be in a terminal state — any week
    ride still UNDER_REVIEW blocks finalization with
    ERR_SETTLEMENT_RIDES_PENDING (HTTP 409)."

    Design: Difficulty/transitive_cascade/fraud_confirm_cascades_ride_review_settlement_reopen_statement_draft
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="LI2", guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    ride1 = rides[0]
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])
    flag = open_fraud_flag(driver["id"], ride1["id"], severity=5,
                           signal_type="INFLATED_RIDE")
    confirm_flag(flag["id"])
    assert read_settlement(settlement["id"])["status"] == "REOPENED"

    response = api.finalize_settlement(settlement["id"], PAY)
    validate_error(response, ApiErrorId.ERR_SETTLEMENT_RIDES_PENDING.value)
    assert read_settlement(settlement["id"])["status"] == "REOPENED"


def test_market_freeze_pauses_program_and_releases_reservation(api):
    """PRD §3.1: "It transitions every IncentiveProgram in that market whose
    status is ACTIVE or DRAFT into PAUSED, and each such pause releases the
    program's promised_make_up_max_cents reservation from the market's
    budget_reserved_cents."
    PRD §2.7: "activation of a GUARANTEE program adds its
    guaranteed_weekly_cents to the reservation and pausing or retiring an
    active GUARANTEE program releases it."

    Design: Difficulty/transitive_cascade/market_freeze_cascades_program_pause_reservation_release
    """
    set_clock()
    market = create_market(market_code="SHV", incentive_budget_cents=1_000_000)
    program = create_guarantee_program(market["id"], guaranteed_weekly_cents=500_000)
    program = activate_program(program["id"])
    assert read_market(market["id"])["budget_reserved_cents"] == 500_000

    market = validate_success(api.freeze_market(market["id"], ADMIN), 200)
    assert market["status"] == "FROZEN"

    program = read_program(program["id"])
    assert program["status"] == "PAUSED", (
        f"freeze must pause the ACTIVE program, got {program['status']}"
    )
    assert program["promised_make_up_max_cents"] == 0

    market = read_market(market["id"])
    assert market["budget_reserved_cents"] == 0
    assert market["budget_available_cents"] == 1_000_000


def test_market_unfreeze_does_not_auto_resume_programs(api):
    """PRD §3.1: "Unfreezing returns the market to ACTIVE but deliberately does
    not auto-resume the paused programs: each program must be resumed
    explicitly, and the market's budget_reserved_cents is recomputed from
    whichever programs are actually ACTIVE after the unfreeze."

    Design: Difficulty/transitive_cascade/market_freeze_cascades_program_pause_reservation_release
    """
    set_clock()
    market = create_market(market_code="SH2", incentive_budget_cents=1_000_000)
    program = create_guarantee_program(market["id"], guaranteed_weekly_cents=500_000)
    activate_program(program["id"])
    validate_success(api.freeze_market(market["id"], ADMIN), 200)

    market = validate_success(api.unfreeze_market(market["id"], ADMIN), 200)
    assert market["status"] == "ACTIVE"
    program = read_program(program["id"])
    assert program["status"] == "PAUSED", (
        f"unfreeze must not auto-resume, got {program['status']}"
    )
    assert market["budget_reserved_cents"] == 0, (
        f"reserved must stay released while the program is PAUSED, got "
        f"{market['budget_reserved_cents']}"
    )


def test_rate_ineligible_cascade_cancels_enrollment_and_releases_capacity(api):
    """PRD §3.2: "When a recompute lands the driver in INELIGIBLE, the cascade
    fires immediately: every IncentiveEnrollment of that driver in ACTIVE
    status is moved to CANCELLED, and each such cancellation releases any
    bonus-zone capacity slot it was holding so the program's headroom is
    recomputed."

    Design: Difficulty/transitive_cascade/rate_ineligible_cascades_enrollment_cancel_capacity_release
    """
    set_clock()
    market = create_market(market_code="GSP", incentive_budget_cents=1_000_000)
    driver1 = create_driver(market["id"], display_name="Driver One")
    driver2 = create_driver(market["id"], display_name="Driver Two")
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=1)
    enr1 = enroll(zone["id"], driver1["id"])
    assert enr1["status"] == "ACTIVE"

    # 1 accept / 19 declines -> acceptance 500 bps < 7500: INELIGIBLE.
    driver1 = validate_success(
        api.record_rate_events(driver1["id"],
                               rate_events_payload(accepted=1, declined=19), OPS),
        200,
    )
    assert driver1["rate_posture"] == "INELIGIBLE"

    enr1 = read_enrollment(enr1["id"])
    assert enr1["status"] == "CANCELLED", (
        f"INELIGIBLE cascade must cancel ACTIVE enrollments, got {enr1['status']}"
    )

    # The released slot admits driver2.
    response = api.enroll_driver(zone["id"], {"driver_id": driver2["id"]}, OPS)
    enr2 = validate_success(response, 201)
    assert enr2["status"] == "ACTIVE", (
        f"capacity-1 slot freed by the cascade must admit the second driver, "
        f"got {enr2['status']}"
    )


def test_rate_ineligible_cascade_is_caused_by_posture_flip(api):
    """PRD §3.2: "When a recompute lands the driver in INELIGIBLE, the cascade
    fires immediately: every IncentiveEnrollment of that driver in ACTIVE
    status is moved to CANCELLED."
    PRD §3.5: "an ACTIVE enrollment may be moved to CANCELLED — by the driver
    themselves, by IncentiveOps, or by the system as part of the
    INELIGIBLE-rate, RESTRICTED-fraud, or deactivation cascades."

    Design: Difficulty/transitive_cascade/rate_ineligible_cascades_enrollment_cancel_capacity_release
    """
    set_clock()
    market = create_market(market_code="GS2", incentive_budget_cents=1_000_000)
    driver = create_driver(market["id"], display_name="Cascade Target")
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=1)
    enr = enroll(zone["id"], driver["id"])

    # 19 offers only -> below the 20-offer minimum: no cascade.
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=1, declined=18), OPS),
        200,
    )
    assert driver["rate_posture"] == "ELIGIBLE", (
        f"below the minimum-evidence constant the posture is left unchanged, "
        f"got {driver['rate_posture']}"
    )
    assert read_enrollment(enr["id"])["status"] == "ACTIVE"

    # The 20th offer completes the evidence: posture flips and the cascade fires.
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=0, declined=1), OPS),
        200,
    )
    assert driver["rate_posture"] == "INELIGIBLE"
    assert read_enrollment(enr["id"])["status"] == "CANCELLED"


# ============================================================================
# priority_pair_validation_conflict
# ============================================================================
def test_pay_draft_settlement_state_error_trumps_budget_error(api):
    """PRD §2.9: "state-machine legality third (ERR_INVALID_STATE); fraud-gating
    fourth (ERR_FRAUD_RESTRICTED); temporal/window rules fifth
    (ERR_PROGRAM_WINDOW_CONFLICT); cross-entity referential coherence sixth
    (ERR_CROSS_MARKET_REFERENCE); eligibility gating seventh
    (ERR_DRIVER_INELIGIBLE); budget checks eighth (ERR_BUDGET_EXCEEDED)."
    PRD §2.9: "Where several of these could fire on the same request, the
    earlier priority wins."
    PRD §3.8: "Payment is permitted from FINALIZED only, requires the market's
    budget_available_cents to cover make_up_cents (over-budget payments are
    refused with ERR_BUDGET_EXCEEDED), adds the make-up to the market's
    budget_spent_cents, sets paid_at_utc."

    Design: Difficulty/priority_pair_validation_conflict/pay_draft_settlement_state_trumps_fiscal
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="MSG", budget=1_000_000, guaranteed_weekly_cents=500_000,
        guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    settlement = compute_settlement(driver["id"], program["id"])
    assert settlement["status"] == "DRAFT"
    assert settlement["make_up_cents"] == 400_000

    # Shrink the ceiling to reserved-only so budget_available is 0.
    market = read_market(market["id"])
    market = validate_success(
        api.update_market(
            market["id"],
            {"incentive_budget_cents": 500_000,
             "expected_market_version": market["version"]},
            ADMIN,
        ),
        200,
    )
    assert market["budget_available_cents"] == 0

    response = api.pay_settlement(settlement["id"], PAY)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    settlement = read_settlement(settlement["id"])
    assert settlement["status"] == "DRAFT"
    assert read_market(market["id"])["budget_spent_cents"] == 0


def test_pay_draft_settlement_never_moves_money(api):
    """PRD §3.8: "Payment is permitted from FINALIZED only, requires the
    market's budget_available_cents to cover make_up_cents (over-budget
    payments are refused with ERR_BUDGET_EXCEEDED), adds the make-up to the
    market's budget_spent_cents, sets paid_at_utc."

    Design: Difficulty/priority_pair_validation_conflict/pay_draft_settlement_state_trumps_fiscal
    """
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code="MS2", budget=1_000_000, guaranteed_weekly_cents=500_000,
        guaranteed_min_rides=1, ride_fares_cents=(100_000,),
    )
    settlement = compute_settlement(driver["id"], program["id"])
    # Ample budget here — but DRAFT alone must still reject the pay.
    response = api.pay_settlement(settlement["id"], PAY)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    settlement = read_settlement(settlement["id"])
    assert settlement["status"] == "DRAFT"
    assert settlement["paid_at_utc"] in (None, "")
    assert read_market(market["id"])["budget_spent_cents"] == 0


def test_program_create_window_conflict_trumps_geo_cell_check(api):
    """PRD §2.9: "state-machine legality third (ERR_INVALID_STATE); fraud-gating
    fourth (ERR_FRAUD_RESTRICTED); temporal/window rules fifth
    (ERR_PROGRAM_WINDOW_CONFLICT); cross-entity referential coherence sixth
    (ERR_CROSS_MARKET_REFERENCE); eligibility gating seventh
    (ERR_DRIVER_INELIGIBLE); budget checks eighth (ERR_BUDGET_EXCEEDED)."
    PRD §2.9: "Where several of these could fire on the same request, the
    earlier priority wins."
    PRD §3.3: "the start must be strictly earlier than the end, or creation
    fails."

    Design: Difficulty/priority_pair_validation_conflict/program_create_temporal_trumps_referential
    """
    set_clock()
    market = create_market(market_code="DSM", geo_cells=["cellA"])

    response = api.create_program(
        {
            "market_id": market["id"],
            "program_type": "BONUS_ZONE",
            "title": "BadZ",
            "window_start_utc": "2026-09-14T00:00:00Z",
            "window_end_utc": "2026-09-07T00:00:00Z",
            "stacking_class": "STACKABLE",
            "excluded_ride_types": [],
            "geo_cell_id": "cellZZZ",
            "zone_multiplier_bps": 15000,
            "capacity": 10,
        },
        OPS,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_WINDOW_CONFLICT.value)


def test_program_create_end_before_start_rejected_alone(api):
    """PRD §3.3: "The window is half-open — a program whose window ends at the
    exact instant another begins does not overlap it — and the start must be
    strictly earlier than the end, or creation fails."

    Design: Difficulty/priority_pair_validation_conflict/program_create_temporal_trumps_referential
    """
    set_clock()
    market = create_market(market_code="DS2", geo_cells=["cellA"])

    response = api.create_program(
        {
            "market_id": market["id"],
            "program_type": "BONUS_ZONE",
            "title": "BadWindow",
            "window_start_utc": "2026-09-14T00:00:00Z",
            "window_end_utc": "2026-09-07T00:00:00Z",
            "stacking_class": "STACKABLE",
            "excluded_ride_types": [],
            "geo_cell_id": "cellA",
            "zone_multiplier_bps": 15000,
            "capacity": 10,
        },
        OPS,
    )
    validate_error(response, ApiErrorId.ERR_PROGRAM_WINDOW_CONFLICT.value)
