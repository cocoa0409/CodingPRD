"""Award tests: eligibility scoring, tier boundaries, pool capacity, vesting
sweep, and source-period state gating."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_partner,
    create_open_period,
    post_line_item,
    compute_period,
    finalize_period,
    setup_active_contract,
    create_stock_program,
    grant_award,
    set_clock,
    TEST_USERS,
)

CONTROLLER = TEST_USERS["corporate_controller_headers"]
HR = TEST_USERS["hr_recruiter_headers"]


def test_grant_rejected_when_source_period_outside_program_window(api):
    """PRD §3.10: "The source period must be FINALIZED or LOCKED, and its own
    period interval must lie entirely within the program's inclusive
    performance window — a period failing either condition is rejected with
    ERR_AWARD_SOURCE_PERIOD_INELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/grant_requires_finalized_source_period
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 9000000, "FINALIZED")
    compute_period(period["id"])
    finalize_period(period["id"])
    # Program window ends before the period does: interval not inside window.
    program = create_stock_program(
        stock_units_pool=1000,
        performance_period_start_date="2027-01-01",
        performance_period_end_date="2027-04-30",
    )
    resp = api.create_award_grant(
        program["id"],
        {"partner_id": setup["partner"]["id"], "source_period_id": period["id"]},
        CONTROLLER,
    )
    validate_error(resp, ApiErrorId.ERR_AWARD_SOURCE_PERIOD_INELIGIBLE)


def test_grant_requires_finalized_source_period(api):
    """PRD §3.10: "The source period must be FINALIZED or LOCKED, and its own
    period interval must lie entirely within the program's inclusive
    performance window — a period failing either condition is rejected with
    ERR_AWARD_SOURCE_PERIOD_INELIGIBLE."

    Design: Difficulty/cross_entity_state_dependency/grant_requires_finalized_source_period
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 9000000, "FINALIZED")
    compute_period(period["id"])  # COMPUTED only — never finalized
    program = create_stock_program(stock_units_pool=1000)
    resp = api.create_award_grant(
        program["id"],
        {"partner_id": setup["partner"]["id"], "source_period_id": period["id"]},
        CONTROLLER,
    )
    validate_error(resp, ApiErrorId.ERR_AWARD_SOURCE_PERIOD_INELIGIBLE)
    program_now = validate_success(api.get_award_program(program["id"], CONTROLLER))
    assert program_now["units_reserved"] == 0
    _, meta = validate_paginated(
        api.list_award_grants(CONTROLLER, params={"program_id": program["id"]})
    )
    assert meta["total_count"] == 0


def test_award_score_tier_boundaries_pick_100_or_200_units(api):
    """PRD §3.10: "Eligibility is inclusive: a score equal to the program's
    eligibility_threshold_score passes; below it, the grant is rejected with
    ERR_AWARD_NOT_ELIGIBLE."
    PRD §3.10: "A STOCK_GRANT awards by tier: a score of at least 90 earns 200
    units; a score of at least 80 earns 100 units."
    PRD §3.10: "The sales component contributes up to 50 points: 50 times the
    ratio of the period's revenue to the 20,000,000-cent sales target, capped
    at the full 50 when revenue meets or exceeds the target ... The profit
    margin component contributes up to 30 points: 30 times the ratio of the
    period's profit margin to the 10% margin target, again capped at full
    marks ... The waste component contributes up to 20 points: 20 times one
    minus the ratio of the period's total waste charges to the 500,000-cent
    waste allowance, with the ratio capped at 1."

    Design: Corner/calculations/award_score_tier_boundaries_pick_100_or_200_units
    """
    setup = setup_active_contract()
    # PP24: revenue 9000000, profit 9000000 -> score 22.5 + 30 + 20 = 72.50
    p24 = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(p24["id"], "REVENUE", 9000000, "FINALIZED")
    compute_period(p24["id"])
    finalize_period(p24["id"])
    # PP25: revenue 18000000, profit 6000000 -> score 45 + 30 + 20 = 95.00
    p25 = create_open_period(setup["restaurant"]["id"], "2027-05-01", "2027-06-01")
    post_line_item(p25["id"], "REVENUE", 18000000, "FINALIZED")
    post_line_item(p25["id"], "LABOR", 12000000, "FINALIZED")
    compute_period(p25["id"])
    finalize_period(p25["id"])
    program = create_stock_program(stock_units_pool=1000)

    resp_low = api.create_award_grant(
        program["id"],
        {"partner_id": setup["partner"]["id"], "source_period_id": p24["id"]},
        CONTROLLER,
    )
    validate_error(resp_low, ApiErrorId.ERR_AWARD_NOT_ELIGIBLE)
    grant = validate_success(
        api.create_award_grant(
            program["id"],
            {"partner_id": setup["partner"]["id"], "source_period_id": p25["id"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert grant["eligibility_score"] == 95.0
    assert grant["units_awarded"] == 200
    assert grant["status"] == "EARNED"
    program_now = validate_success(api.get_award_program(program["id"], CONTROLLER))
    assert program_now["units_reserved"] == 200


def test_pool_capacity_exhaustion_boundary(api):
    """PRD §3.10: "Stock draws against the pool: if the program's
    units_reserved plus the tier's units would exceed the stock_units_pool,
    the grant is rejected with ERR_AWARD_POOL_EXHAUSTED; otherwise the units
    are added to units_reserved."

    Design: Corner/calculations/pool_capacity_exhaustion_boundary
    """
    partner2 = create_partner(full_name="Sam Reed", email="sr@x.com")
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 18000000, "FINALIZED")
    post_line_item(period["id"], "LABOR", 12000000, "FINALIZED")
    compute_period(period["id"])
    finalize_period(period["id"])  # score 95 -> tier 200 units
    program = create_stock_program(stock_units_pool=250)
    grant1 = validate_success(
        api.create_award_grant(
            program["id"],
            {"partner_id": setup["partner"]["id"], "source_period_id": period["id"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    assert grant1["units_awarded"] == 200
    resp_second = api.create_award_grant(
        program["id"],
        {"partner_id": partner2["id"], "source_period_id": period["id"]},
        CONTROLLER,
    )
    validate_error(resp_second, ApiErrorId.ERR_AWARD_POOL_EXHAUSTED)
    program_now = validate_success(api.get_award_program(program["id"], CONTROLLER))
    assert program_now["units_reserved"] == 200


def test_grant_vesting_sweep_after_vesting_days(api):
    """PRD §3.10: "A CorporateController moves a grant from EARNED to VESTING.
    From there the clock does the rest: once the logical clock's date reaches
    the grant's created_at date plus 365 days, the sweep moves the grant to
    VESTED."
    PRD §2.10: "A stock grant vests 365 days after the grant's creation date."

    Design: Corner/state_machines/grant_vesting_sweep_after_vesting_days
    """
    setup = setup_active_contract()
    period = create_open_period(setup["restaurant"]["id"], "2027-04-01", "2027-05-01")
    set_clock("2027-04-15T00:00:00Z")
    post_line_item(period["id"], "REVENUE", 9000000, "FINALIZED")
    compute_period(period["id"])
    finalize_period(period["id"])  # score 72.50 fails stock tier; use a high-score period
    high = create_open_period(setup["restaurant"]["id"], "2027-05-01", "2027-06-01")
    post_line_item(high["id"], "REVENUE", 18000000, "FINALIZED")
    post_line_item(high["id"], "LABOR", 12000000, "FINALIZED")
    compute_period(high["id"])
    finalize_period(high["id"])
    program = create_stock_program(stock_units_pool=1000)
    grant = validate_success(
        api.create_award_grant(
            program["id"],
            {"partner_id": setup["partner"]["id"], "source_period_id": high["id"]},
            CONTROLLER,
        ),
        expected_status=201,
    )
    validate_success(api.vest_award_grant(grant["id"], CONTROLLER))
    assert grant["units_awarded"] == 200

    # created_at is 2027-04-15; the span 2027-04-15 -> 2028-04-15 is 366 days
    # (2028 is a leap year), so +365 days lands on 2028-04-14.
    set_clock("2028-04-13T00:00:00Z")  # 364 days after creation — not yet vested
    fetched = validate_success(api.get_award_grant(grant["id"], CONTROLLER))
    assert fetched["status"] == "VESTING"
    set_clock("2028-04-14T00:00:00Z")  # 365 days after creation -> VESTED
    fetched = validate_success(api.get_award_grant(grant["id"], CONTROLLER))
    assert fetched["status"] == "VESTED"
    program_now = validate_success(api.get_award_program(program["id"], CONTROLLER))
    assert program_now["units_reserved"] == 200
