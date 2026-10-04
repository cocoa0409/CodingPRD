"""Boundary precision, cross-entity state dependency, and temporal overlap
(difficulty queue A)."""

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
    compute_statement,
    create_active_challenge_program,
    create_active_zone_program,
    create_driver,
    create_guarantee_program,
    create_market,
    create_market_with_driver,
    create_streak_program,
    enroll,
    finalize_settlement,
    pay_settlement,
    rate_events_payload,
    read_driver,
    read_enrollment,
    read_market,
    read_program,
    read_statement,
    set_clock,
    setup_published_statement,
    validate_error,
    validate_paginated,
    validate_success,
    ApiErrorId,
)


# ============================================================================
# boundary_precision_check
# ============================================================================
def test_acceptance_exactly_9000_yields_eligible(api):
    """PRD §3.2: "The boundary comparisons are exactly as stated — an
    acceptance rate of exactly 9000 basis points satisfies the ELIGIBLE
    acceptance threshold."
    PRD §3.2: "if acceptance_rate_bps is at least 9000 and
    cancellation_rate_bps is at most 1000, the posture is ELIGIBLE."

    Design: Difficulty/boundary_precision_check/acceptance_rate_exactly_9000_is_eligible_8500_is_probation
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="ELP")
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=18, declined=2), OPS),
        200,
    )
    assert driver["offers_total"] == 20
    assert driver["acceptance_rate_bps"] == 9000, (
        f"floor(10000*18/20) = 9000, got {driver['acceptance_rate_bps']}"
    )
    assert driver["rate_posture"] == "ELIGIBLE", (
        f"9000 >= 9000 must be ELIGIBLE, got {driver['rate_posture']}"
    )


def test_acceptance_8500_one_offer_short_yields_probation(api):
    """PRD §3.2: "Failing that, if acceptance_rate_bps is at least 7500 and
    cancellation_rate_bps is at most 2000, the posture is PROBATION."

    Design: Difficulty/boundary_precision_check/acceptance_rate_exactly_9000_is_eligible_8500_is_probation
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="EL2")
    driver = validate_success(
        api.record_rate_events(driver["id"],
                               rate_events_payload(accepted=17, declined=3), OPS),
        200,
    )
    assert driver["acceptance_rate_bps"] == 8500, (
        f"floor(10000*17/20) = 8500, got {driver['acceptance_rate_bps']}"
    )
    assert driver["rate_posture"] == "PROBATION", (
        f"8500 misses ELIGIBLE but satisfies the PROBATION floor, got "
        f"{driver['rate_posture']}"
    )


def test_challenge_target_reached_exactly_at_nth_ride(api):
    """PRD §3.5: "for a CHALLENGE, when progress_count equals
    challenge_ride_target — the system moves the enrollment to COMPLETED and
    sets its payout under the stacking resolution of §3.7."
    PRD §3.6: "Streak and challenge completions move the enrollment to
    COMPLETED and add the payout to the market's budget_spent_cents."

    Design: Difficulty/boundary_precision_check/challenge_target_reached_exactly_at_nth_ride
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="FAT", budget=10_000_000)
    program = create_active_challenge_program(market["id"], challenge_ride_target=2,
                                              challenge_payout_cents=12_000)
    enrollment = enroll(program["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)

    enrollment = read_enrollment(enrollment["id"])
    assert enrollment["progress_count"] == 1
    assert enrollment["status"] == "ACTIVE"
    assert enrollment["payout_cents"] == 0, (
        f"target-1 of 2 pays nothing yet, got {enrollment['payout_cents']}"
    )

    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    enrollment = read_enrollment(enrollment["id"])
    assert enrollment["progress_count"] == 2
    assert enrollment["status"] == "COMPLETED"
    assert enrollment["payout_cents"] == 12_000


def test_challenge_payout_lands_in_market_budget_spent_once(api):
    """PRD §3.6: "Streak and challenge completions move the enrollment to
    COMPLETED and add the payout to the market's budget_spent_cents."
    PRD §3.7: "A CHALLENGE pays its full challenge_payout_cents in one shot
    when the target is reached."

    Design: Difficulty/boundary_precision_check/challenge_target_reached_exactly_at_nth_ride
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="FA2", budget=10_000_000)
    program = create_active_challenge_program(market["id"], challenge_ride_target=2,
                                              challenge_payout_cents=12_000)
    enroll(program["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    assert read_market(market["id"])["budget_spent_cents"] == 0

    complete_ride_end_to_end(driver, market["id"], base_fare_cents=8000)
    market = read_market(market["id"])
    assert market["budget_spent_cents"] == 12_000, (
        f"the target ride pays exactly once, got {market['budget_spent_cents']}"
    )


# ============================================================================
# cross_entity_state_dependency
# ============================================================================
def test_enrollment_into_draft_program_rejected(api):
    """PRD §3.3: "New programs are born in DRAFT status."
    PRD §3.3: "Activation is the gate where a program becomes real."
    PRD §3.5: "Creation enforces a stack of gates, and their evaluation order
    matters."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_program_active
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="ICT")
    program = create_streak_program(market["id"])  # stays DRAFT

    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    enrollments, meta = validate_paginated(
        api.list_program_enrollments(program["id"], OPS)
    )
    assert enrollments == [] and meta["total_count"] == 0


def test_enrollment_into_paused_program_rejected(api):
    """PRD §3.3: "Pausing an ACTIVE program — either by explicit IncentiveOps
    action or via the market freeze cascade — moves it to PAUSED."
    PRD §3.5: "Enrollment is the junction between a Driver and an
    IncentiveProgram."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_program_active
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="IC2")
    program = create_streak_program(market["id"])
    activate_program(program["id"])
    validate_success(api.pause_program(program["id"], OPS), 200)

    response = api.enroll_driver(program["id"], {"driver_id": driver["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)


def test_statement_publish_blocked_while_settlement_finalized(api):
    """PRD §3.10: "A statement is born DRAFT and becomes PUBLISHED only when
    every GuaranteeSettlement for the same driver and week is PAID or VOID;
    publishing while any week settlement sits in DRAFT, FINALIZED, or REOPENED
    is refused with ERR_STATEMENT_SETTLEMENTS_OPEN (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/statement_publish_requires_settlements_paid_or_void
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        _setup_finalized_with_statement(api, market_code="PIR")
    )

    response = api.publish_statement(statement["id"], PAY)
    validate_error(response, ApiErrorId.ERR_STATEMENT_SETTLEMENTS_OPEN.value)

    statement = read_statement(statement["id"])
    assert statement["status"] == "DRAFT"


def test_statement_publish_succeeds_after_settlement_paid(api):
    """PRD §3.10: "A statement is born DRAFT and becomes PUBLISHED only when
    every GuaranteeSettlement for the same driver and week is PAID or VOID."
    PRD §3.8: "triggers recompute of the week's EarningsStatement
    make_up_total_cents and total_cents."

    Design: Difficulty/cross_entity_state_dependency/statement_publish_requires_settlements_paid_or_void
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        _setup_finalized_with_statement(api, market_code="PI2")
    )

    settlement = pay_settlement(settlement["id"])
    statement = validate_success(api.publish_statement(statement["id"], PAY), 200)
    assert statement["status"] == "PUBLISHED"
    assert statement["make_up_total_cents"] == 400_000


def _setup_finalized_with_statement(api, market_code):
    from test_helpers import setup_guarantee_with_rides  # local to avoid cycle
    market, driver, program, enrollment, rides = setup_guarantee_with_rides(
        market_code=market_code, guaranteed_min_rides=1,
        ride_fares_cents=(100_000,), tips_cents=500,
    )
    settlement = compute_settlement(driver["id"], program["id"])
    settlement = finalize_settlement(settlement["id"])
    statement = compute_statement(driver["id"])
    return market, driver, program, enrollment, rides, settlement, statement


# ============================================================================
# resource_temporal_overlap
# ============================================================================
def test_zone_overlap_rejected_and_adjacency_allowed(api):
    """PRD §3.3: "The window is half-open — a program whose window ends at the
    exact instant another begins does not overlap it."
    PRD §3.3: "when the program is a BONUS_ZONE, only when no other ACTIVE zone
    program in the same market covers the same geo_cell_id with an overlapping
    half-open window; ... A window or overlap violation surfaces as
    ERR_PROGRAM_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/bonus_zone_same_cell_half_open_overlap_rejected_adjacency_allowed
    """
    set_clock()
    market = create_market(market_code="EUG", geo_cells=["cellA", "cellB"])
    from test_helpers import create_zone_program
    z1 = create_zone_program(
        market["id"], geo_cell_id="cellA",
        window_start_utc="2026-09-07T00:00:00Z",
        window_end_utc="2026-09-14T00:00:00Z",
    )
    activate_program(z1["id"])

    # Overlapping window [09-10, 09-17) on the same cell.
    z2 = create_zone_program(
        market["id"], geo_cell_id="cellA", zone_multiplier_bps=12000,
        window_start_utc="2026-09-10T00:00:00Z",
        window_end_utc="2026-09-17T00:00:00Z",
    )
    response = api.activate_program(z2["id"], OPS)
    validate_error(response, ApiErrorId.ERR_PROGRAM_WINDOW_CONFLICT.value)
    assert read_program(z2["id"])["status"] == "DRAFT"

    # Adjacent window [09-14, 09-21): half-open means no overlap.
    z3 = create_zone_program(
        market["id"], geo_cell_id="cellA", zone_multiplier_bps=12000,
        window_start_utc="2026-09-14T00:00:00Z",
        window_end_utc="2026-09-21T00:00:00Z",
    )
    z3 = validate_success(api.activate_program(z3["id"], OPS), 200)
    assert z3["status"] == "ACTIVE"


def test_zone_overlap_only_blocks_same_cell(api):
    """PRD §3.3: "when the program is a BONUS_ZONE, only when no other ACTIVE
    zone program in the same market covers the same geo_cell_id with an
    overlapping half-open window."

    Design: Difficulty/resource_temporal_overlap/bonus_zone_same_cell_half_open_overlap_rejected_adjacency_allowed
    """
    set_clock()
    market = create_market(market_code="EU2", geo_cells=["cellA", "cellB"])
    from test_helpers import create_zone_program
    z1 = create_zone_program(
        market["id"], geo_cell_id="cellA",
        window_start_utc="2026-09-07T00:00:00Z",
        window_end_utc="2026-09-14T00:00:00Z",
    )
    activate_program(z1["id"])

    # Same window but a different cell: permitted.
    z2 = create_zone_program(
        market["id"], geo_cell_id="cellB", zone_multiplier_bps=12000,
        window_start_utc="2026-09-07T00:00:00Z",
        window_end_utc="2026-09-14T00:00:00Z",
    )
    z2 = validate_success(api.activate_program(z2["id"], OPS), 200)
    assert z2["status"] == "ACTIVE"


def test_zone_capacity_blocks_extra_enrollment(api):
    """PRD §3.3: "A BONUS_ZONE program requires geo_cell_id — which must be a
    member of the owning market's geo_cells, with violations rejected as
    ERR_GEO_CELL_UNKNOWN — plus zone_multiplier_bps (strictly greater than
    10000, since 10000 represents par) and capacity (the maximum number of
    concurrently ACTIVE enrollments the zone supports; an omitted capacity
    means the zone is uncapped)."
    PRD §3.5: "a BONUS_ZONE program with a capacity must have a free slot — a
    full zone is refused with ERR_PROGRAM_WINDOW_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/bonus_zone_capacity_aggregate_occupancy_blocks_extra_enrollment
    """
    set_clock()
    market = create_market(market_code="BHM", incentive_budget_cents=1_000_000)
    driver1 = create_driver(market["id"], display_name="Cap Carl")
    driver2 = create_driver(market["id"], display_name="Cap Cara")
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=1)

    enr1 = enroll(zone["id"], driver1["id"])
    assert enr1["status"] == "ACTIVE"

    response = api.enroll_driver(zone["id"], {"driver_id": driver2["id"]}, OPS)
    validate_error(response, ApiErrorId.ERR_PROGRAM_WINDOW_CONFLICT.value)


def test_zone_uncapped_when_capacity_omitted(api):
    """PRD §3.3: "capacity (the maximum number of concurrently ACTIVE
    enrollments the zone supports; an omitted capacity means the zone is
    uncapped)."

    Design: Difficulty/resource_temporal_overlap/bonus_zone_capacity_aggregate_occupancy_blocks_extra_enrollment
    """
    set_clock()
    market = create_market(market_code="BH2", incentive_budget_cents=1_000_000)
    driver1 = create_driver(market["id"], display_name="Uncap Una")
    driver2 = create_driver(market["id"], display_name="Uncap Uli")
    zone_payload = {
        "market_id": market["id"],
        "program_type": "BONUS_ZONE",
        "title": "Uncapped Zone",
        "window_start_utc": "2026-09-07T00:00:00Z",
        "window_end_utc": "2026-09-14T00:00:00Z",
        "stacking_class": "STACKABLE",
        "excluded_ride_types": [],
        "geo_cell_id": "cellA",
        "zone_multiplier_bps": 15000,
    }
    zone = validate_success(api.create_program(zone_payload, OPS), 201)
    activate_program(zone["id"])

    enr1 = enroll(zone["id"], driver1["id"])
    enr2 = enroll(zone["id"], driver2["id"])
    assert enr1["status"] == "ACTIVE"
    assert enr2["status"] == "ACTIVE"


# ============================================================================
# compensating_invariant
# ============================================================================
def test_market_budget_conservation_across_activate_payout_pause(api):
    """PRD §2.7: "Each Market maintains a weekly incentive budget as three
    derived counters: budget_spent_cents ... budget_reserved_cents ... and
    budget_available_cents (the weekly incentive_budget_cents minus spent minus
    reserved)."
    PRD §2.7: "Reservations move in lockstep with program state: activation of
    a GUARANTEE program adds its guaranteed_weekly_cents to the reservation and
    pausing or retiring an active GUARANTEE program releases it."

    Design: Difficulty/compensating_invariant/market_budget_conservation_across_activate_payout_pause
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="CAK", budget=10_000_000)
    guarantee = create_guarantee_program(market["id"], guaranteed_weekly_cents=500_000)
    activate_program(guarantee["id"])
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    enroll(zone["id"], driver["id"])

    market = read_market(market["id"])
    assert (
        market["budget_spent_cents"],
        market["budget_reserved_cents"],
        market["budget_available_cents"],
    ) == (0, 500_000, 9_500_000)
    assert (
        market["budget_spent_cents"] + market["budget_reserved_cents"]
        + market["budget_available_cents"] == 10_000_000
    )

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=333)

    market = read_market(market["id"])
    assert (
        market["budget_spent_cents"],
        market["budget_reserved_cents"],
        market["budget_available_cents"],
    ) == (166, 500_000, 9_499_834)

    validate_success(api.pause_program(guarantee["id"], OPS), 200)
    market = read_market(market["id"])
    assert (
        market["budget_spent_cents"],
        market["budget_reserved_cents"],
        market["budget_available_cents"],
    ) == (166, 0, 9_999_834)


def test_market_available_never_negative_after_reserve_and_spend(api):
    """PRD §2.7: "The available figure is never negative — any operation that
    would drive it below zero is rejected with ERR_BUDGET_EXCEEDED (HTTP 402)."
    PRD §3.3: "Successful activation of a GUARANTEE program sets its
    promised_make_up_max_cents to guaranteed_weekly_cents and adds that amount
    to the market's budget_reserved_cents."

    Design: Difficulty/compensating_invariant/market_budget_conservation_across_activate_payout_pause
    """
    set_clock()
    market, driver = create_market_with_driver(market_code="CA2", budget=1_000_000)
    guarantee = create_guarantee_program(market["id"], guaranteed_weekly_cents=700_000)
    activate_program(guarantee["id"])
    zone = create_active_zone_program(market["id"], geo_cell_id="cellA",
                                      zone_multiplier_bps=15000, capacity=10)
    enroll(zone["id"], driver["id"])

    set_clock(WEEK_MID)
    complete_ride_end_to_end(driver, market["id"], base_fare_cents=100_000)

    market = read_market(market["id"])
    # zone bonus floor(100000 * 5000 / 10000) = 50000 spent.
    assert market["budget_spent_cents"] == 50_000
    assert market["budget_reserved_cents"] == 700_000
    assert market["budget_available_cents"] == 250_000
    assert (
        market["budget_spent_cents"] + market["budget_reserved_cents"]
        + market["budget_available_cents"] == market["incentive_budget_cents"]
    )


def test_statement_invariant_holds_across_dispute_amendment(api):
    """PRD §3.10: "the invariant total_cents equals base_fares_cents plus
    tips_cents_total plus bonus_total_cents plus make_up_total_cents plus
    adjustments_cents is maintained on every mutation."
    PRD §3.10: "moves the statement to AMENDED with the signed adjustment added
    into adjustments_cents and total_cents recomputed under the invariant."

    Design: Difficulty/compensating_invariant/statement_reconciliation_invariant_across_dispute_amendment
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        setup_published_statement(market_code="DAY", guaranteed_min_rides=1,
                                  ride_fares_cents=(100_000,), tips_cents=500)
    )
    assert statement["total_cents"] == (
        statement["base_fares_cents"] + statement["tips_cents_total"]
        + statement["bonus_total_cents"] + statement["make_up_total_cents"]
        + statement["adjustments_cents"]
    )
    assert statement["total_cents"] == 500_500, (
        f"100000 + 500 + 0 + 400000 + 0 = 500500, got {statement['total_cents']}"
    )

    from test_helpers import file_statement_appeal
    appeal = file_statement_appeal(driver, statement["id"], reason="bonus missing")
    validate_success(api.start_appeal_review(appeal["id"], PAY), 200)
    appeal = validate_success(
        api.resolve_appeal(appeal["id"],
                           {"outcome": "OVERTURNED", "adjustment_cents": -20_000},
                           PAY),
        200,
    )
    assert appeal["status"] == "RESOLVED_OVERTURNED"

    statement = read_statement(statement["id"])
    assert statement["status"] == "AMENDED"
    assert statement["adjustments_cents"] == -20_000
    assert statement["total_cents"] == 480_500, (
        f"500500 - 20000 = 480500, got {statement['total_cents']}"
    )
    assert statement["total_cents"] == (
        statement["base_fares_cents"] + statement["tips_cents_total"]
        + statement["bonus_total_cents"] + statement["make_up_total_cents"]
        + statement["adjustments_cents"]
    )


def test_statement_upheld_appeal_returns_published_unchanged(api):
    """PRD §3.10: "Upholding a STATEMENT appeal returns the statement to
    PUBLISHED unchanged."
    PRD §3.10: "the invariant total_cents equals base_fares_cents plus
    tips_cents_total plus bonus_total_cents plus make_up_total_cents plus
    adjustments_cents is maintained on every mutation."

    Design: Difficulty/compensating_invariant/statement_reconciliation_invariant_across_dispute_amendment
    """
    market, driver, program, enrollment, rides, settlement, statement = (
        setup_published_statement(market_code="DA2", guaranteed_min_rides=1,
                                  ride_fares_cents=(100_000,), tips_cents=500)
    )
    from test_helpers import file_statement_appeal
    appeal = file_statement_appeal(driver, statement["id"], reason="unfair")
    validate_success(api.start_appeal_review(appeal["id"], PAY), 200)
    appeal = validate_success(
        api.resolve_appeal(appeal["id"], {"outcome": "UPHELD"}, PAY), 200
    )
    assert appeal["status"] == "RESOLVED_UPHELD"

    statement = read_statement(statement["id"])
    assert statement["status"] == "PUBLISHED"
    assert statement["adjustments_cents"] == 0
    assert statement["total_cents"] == 500_500
