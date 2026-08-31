"""Withdrawal liability: allocation, the twenty-year cap, certification and demand."""

from test_helpers import (
    ACTUARY_USER_ID,
    ADMIN_USER_ID,
    TEST_USERS,
    ApiErrorId,
    assert_fund_pool_split,
    assert_withdrawal_assessment,
    certify_withdrawal,
    contribution_line_payload,
    create_contribution_report_payload,
    create_employer,
    create_fund,
    create_trustee,
    create_withdrawal_assessment_payload,
    employer_version,
    fund_version,
    list_installments,
    make_administrator_headers,
    make_employer_headers,
    open_withdrawal,
    read_employer,
    read_fund,
    read_withdrawal,
    set_clock,
    setup_assessment_under_review,
    setup_de_minimis_boundary_employers,
    setup_frozen_board_with_certified_assessment,
    setup_tiny_base_unit_employer,
    setup_withdrawn_employer_after_a_successful_filing,
    setup_withdrawn_employer_holding_a_live_report,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["fund_administrator_headers"]
ACTUARY = TEST_USERS["actuary_headers"]


def test_the_cap_collapses_the_collection_without_reopening_the_allocation(api):
    """PRD §3.9: "Fourth, the uncapped number of years is the net liability
    divided by the annual payment and rounded **up** to a whole number. Fifth,
    the cap is tested: if the uncapped number of years exceeds 20, then
    `twenty_year_cap_applied` is true, `schedule_years` is 20, and
    `capped_liability_cents` is the annual payment multiplied by 20; otherwise
    `twenty_year_cap_applied` is false, `schedule_years` is the uncapped figure,
    and `capped_liability_cents` equals `net_liability_cents`. Sixth and last,
    `de_minimis_reduction_cents` is **not** recomputed after the cap applies —
    the cap limits collection, it does not reopen the allocation."
    PRD §3.9: "Third, `annual_payment_cents` is that average multiplied by the
    employer's `contribution_rate_millicents_per_hour` and divided by 1,000 —
    millicents to cents — rounded half up to whole cents; if the result is 0
    there is no finite schedule and the request is refused with
    `ERR_NO_PAYMENT_BASE`."

    Design: Difficulty/combinatorial_formula/withdrawal_schedule_cap_evaluation_order_pinned
    """
    base = setup_tiny_base_unit_employer()

    assessment = validate_success(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(
                base["employer"]["id"], fund_version(base["fund"]["id"])
            ),
            ADMIN,
        ),
        201,
    )

    assert_withdrawal_assessment(assessment)
    assert assessment["net_liability_cents"] == 60_000_000
    assert assessment["de_minimis_reduction_cents"] == 0, (
        "the reduction is not re-derived once the cap fires"
    )
    assert assessment["annual_payment_cents"] == 82550
    assert assessment["twenty_year_cap_applied"] is True
    assert assessment["schedule_years"] == 20
    assert assessment["capped_liability_cents"] == 1651000, "82550 times twenty"


def test_the_capped_assessment_still_reports_its_full_untouched_allocation(api):
    """PRD §3.9: "With the fraction fixed, `raw_allocation_cents` is the pool
    multiplied by the fraction, rounded half up to whole cents."
    PRD §3.9: "Under `PRESUMPTIVE`, the fraction is the sum of all five entries
    of the employer's `prior_year_contributions_cents` divided by the sum of all
    five entries of the fund's `pool_prior_year_contributions_cents`."
    PRD §3.9: "The assessment opens in `DRAFT` with `certified_by_user_id`,
    `demanded_on`, `review_grounds` and `accelerated_balance_cents` all null and
    `twenty_year_cap_applied` false; crucially, **no unfunded vested benefit is
    allocated at this point**, because a draft has not been certified."
    PRD §3.9: "Opening an assessment moves the employer to `WITHDRAWN` — from
    `ACTIVE` or from `SUSPENDED` alike, so long as it is not already withdrawn —
    and from that moment the employer may file no further contribution reports."

    Design: Difficulty/combinatorial_formula/withdrawal_schedule_cap_evaluation_order_pinned
    """
    base = setup_tiny_base_unit_employer()

    assessment = open_withdrawal(base["fund"]["id"], base["employer"]["id"])

    assert assessment["employer_share_fraction"] == 0.6000000000
    assert assessment["raw_allocation_cents"] == 60_000_000
    assert assessment["status"] == "DRAFT"
    assert assessment["certified_by_user_id"] is None
    assert assessment["demanded_on"] is None
    assert assessment["review_grounds"] is None
    assert assessment["accelerated_balance_cents"] is None

    assert read_employer(base["employer"]["id"])["status"] == "WITHDRAWN"

    fund = read_fund(base["fund"]["id"])
    assert fund["allocated_uvb_cents"] == 0, "a DRAFT allocates nothing"
    assert_fund_pool_split(fund)


def test_a_raw_allocation_of_exactly_ten_million_keeps_the_whole_de_minimis(api):
    """PRD §3.9: "The de-minimis amount is the smaller of 750,000 cents and the
    fund's `total_uvb_cents` multiplied by 75 basis points, divided by 10,000 and
    rounded half up to whole cents. The phase-out excess is the raw allocation
    less 10,000,000 cents, floored at zero. `de_minimis_reduction_cents` is the
    de-minimis amount less that excess, floored at zero. `net_liability_cents` is
    `raw_allocation_cents` less `de_minimis_reduction_cents`, and that net figure
    is the amount ultimately charged against the pool."
    PRD §3.9: "The phase-out boundary is exact and is worth stating: because the
    excess is measured against 10,000,000 cents, a raw allocation of exactly
    10,000,000 cents keeps the whole de-minimis reduction, while a raw allocation
    of 10,000,001 cents loses precisely one cent of it."

    Design: Difficulty/boundary_precision_check/de_minimis_phaseout_at_exactly_one_hundred_thousand
    """
    base = setup_de_minimis_boundary_employers()

    at_boundary = open_withdrawal(base["fund"]["id"], base["at_boundary"]["id"])

    assert at_boundary["raw_allocation_cents"] == 10_000_000
    assert at_boundary["de_minimis_reduction_cents"] == 750_000
    assert at_boundary["net_liability_cents"] == 9_250_000
    assert at_boundary["annual_payment_cents"] == 825500
    assert at_boundary["schedule_years"] == 12
    assert at_boundary["twenty_year_cap_applied"] is False


def test_one_cent_past_the_phase_out_start_costs_exactly_one_cent_of_relief(api):
    """PRD §3.9: "The phase-out boundary is exact and is worth stating: because
    the excess is measured against 10,000,000 cents, a raw allocation of exactly
    10,000,000 cents keeps the whole de-minimis reduction, while a raw allocation
    of 10,000,001 cents loses precisely one cent of it."
    PRD §3.9: "The employer's `employer_share_fraction` is computed according to
    the chosen method and, in both variants, is rounded half up to exactly ten
    decimal places **before** it is used to multiply anything; multiplying by the
    unrounded fraction produces different cents on realistic inputs and is not an
    acceptable substitute."
    PRD §3.1: "`unallocated_uvb_cents` is always the fund's `total_uvb_cents`
    less its `allocated_uvb_cents`, and `allocated_uvb_cents` is the sum of the
    net liability of every withdrawal assessment against this fund's employers
    whose status is `CERTIFIED`, `DEMANDED`, `REVIEW_REQUESTED`,
    `PAYMENT_ACTIVE`, `ACCELERATED` or `SATISFIED`. Assessments still in `DRAFT`
    contribute nothing."

    Design: Difficulty/boundary_precision_check/de_minimis_phaseout_at_exactly_one_hundred_thousand
    """
    base = setup_de_minimis_boundary_employers()
    open_withdrawal(base["fund"]["id"], base["at_boundary"]["id"])

    over_boundary = open_withdrawal(base["fund"]["id"], base["over_boundary"]["id"])

    assert over_boundary["employer_share_fraction"] == 0.1000000100
    assert over_boundary["raw_allocation_cents"] == 10_000_001
    assert over_boundary["de_minimis_reduction_cents"] == 749_999
    assert over_boundary["net_liability_cents"] == 9_250_002

    fund = read_fund(base["fund"]["id"])
    assert fund["allocated_uvb_cents"] == 0, "neither assessment has been certified"
    assert fund["unallocated_uvb_cents"] == 100_000_000


def test_a_frozen_board_cannot_issue_the_payment_demand(api):
    """PRD §3.9: "Demanding payment is the administrator's act, and it is fenced
    from the actuary's. The assessment must be `CERTIFIED`; the fund's
    `governance_posture` must not be `FROZEN`, and a demand issued by a board
    without both bargaining parties represented is refused with
    `ERR_FUND_GOVERNANCE_FROZEN`; the assessment's `annual_payment_cents` must be
    greater than 0; and the administrator issuing the demand must not be the same
    identity recorded in `certified_by_user_id`, an overlap being refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.2: "If either count is 0, `governance_posture` is `FROZEN` — a board
    missing a bargaining party entirely cannot act at all."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_demand_blocked_by_frozen_fund_posture
    """
    base = setup_frozen_board_with_certified_assessment()

    assert read_fund(base["fund"]["id"])["governance_posture"] == "FROZEN"

    validate_error(
        api.demand_withdrawal_assessment(
            base["assessment"]["id"], make_administrator_headers(ADMIN_USER_ID)
        ),
        ApiErrorId.ERR_FUND_GOVERNANCE_FROZEN.value,
    )

    unchanged = read_withdrawal(base["assessment"]["id"])
    assert unchanged["status"] == "CERTIFIED"
    assert unchanged["demanded_on"] is None

    _rows, meta = validate_paginated(
        api.list_installments(base["assessment"]["id"], ADMIN)
    )
    assert meta["total_count"] == 0


def test_seating_both_parties_opens_the_board_and_lets_the_same_demand_through(api):
    """PRD §3.2: "Only when both counts are equal and each is at least two is the
    posture `OPEN`."
    PRD §3.9: "A demand stamps `demanded_on` with the logical clock date, moves
    the assessment to `DEMANDED`, and mints exactly `schedule_years` payment
    installments, each `SCHEDULED`, each carrying its `assessment_id` and a
    one-based `installment_number`, and each with `paid_on` null."
    PRD §3.9: "Certifying stamps the acting actuary's opaque identity into
    `certified_by_user_id`, moves the assessment from `DRAFT` to `CERTIFIED`,
    adds the assessment's `net_liability_cents` to the fund's
    `allocated_uvb_cents`, recomputes `unallocated_uvb_cents` from the new
    allocated figure, and increments the fund's `version` by 1."

    Design: Difficulty/cross_entity_state_dependency/withdrawal_demand_blocked_by_frozen_fund_posture
    """
    base = setup_frozen_board_with_certified_assessment()
    api.demand_withdrawal_assessment(
        base["assessment"]["id"], make_administrator_headers(ADMIN_USER_ID)
    )

    create_trustee(base["fund"]["id"], "UNION", full_name="Union Trustee One")
    create_trustee(base["fund"]["id"], "UNION", full_name="Union Trustee Two")
    create_trustee(base["fund"]["id"], "EMPLOYER", full_name="Employer Trustee One")
    create_trustee(base["fund"]["id"], "EMPLOYER", full_name="Employer Trustee Two")

    assert read_fund(base["fund"]["id"])["governance_posture"] == "OPEN"

    demanded = validate_success(
        api.demand_withdrawal_assessment(
            base["assessment"]["id"], make_administrator_headers(ADMIN_USER_ID)
        )
    )

    assert demanded["status"] == "DEMANDED"
    assert demanded["demanded_on"] == "2026-04-01"

    _rows, meta = validate_paginated(
        api.list_installments(base["assessment"]["id"], ADMIN)
    )
    assert meta["total_count"] == 5

    fund = read_fund(base["fund"]["id"])
    assert fund["allocated_uvb_cents"] == 25_000_000
    assert fund["unallocated_uvb_cents"] == 75_000_000


def test_a_withdrawn_employer_may_no_longer_file_for_a_fresh_work_period(api):
    """PRD §3.3: "An employer whose `status` is `WITHDRAWN` may no longer file at
    all, and the attempt returns `ERR_EMPLOYER_WITHDRAWN`."
    PRD §3.9: "Opening an assessment moves the employer to `WITHDRAWN` — from
    `ACTIVE` or from `SUSPENDED` alike, so long as it is not already withdrawn —
    and from that moment the employer may file no further contribution reports."

    Design: Difficulty/cross_entity_state_dependency/report_intake_blocked_by_withdrawn_employer
    """
    base = setup_withdrawn_employer_after_a_successful_filing()
    employer_id = base["employer"]["id"]

    assert base["march_report"]["filing_status"] == "SUBMITTED", (
        "the identical filing succeeded while the employer was still ACTIVE"
    )
    assert read_employer(employer_id)["status"] == "WITHDRAWN"

    payload = create_contribution_report_payload(
        employer_id,
        "2026-04",
        employer_version(employer_id),
        [contribution_line_payload(base["participant"]["id"], 100.00, 400_000)],
    )

    validate_error(
        api.create_contribution_report(payload, make_employer_headers(employer_id)),
        ApiErrorId.ERR_EMPLOYER_WITHDRAWN.value,
    )


def test_the_refused_filing_adds_no_report_and_leaves_the_draft_assessment_alone(api):
    """PRD §3.3: "An employer whose `status` is `WITHDRAWN` may no longer file at
    all, and the attempt returns `ERR_EMPLOYER_WITHDRAWN`."
    PRD §3.9: "The assessment opens in `DRAFT` with `certified_by_user_id`,
    `demanded_on`, `review_grounds` and `accelerated_balance_cents` all null and
    `twenty_year_cap_applied` false; crucially, **no unfunded vested benefit is
    allocated at this point**, because a draft has not been certified."

    Design: Difficulty/cross_entity_state_dependency/report_intake_blocked_by_withdrawn_employer
    """
    base = setup_withdrawn_employer_after_a_successful_filing()
    employer_id = base["employer"]["id"]

    payload = create_contribution_report_payload(
        employer_id,
        "2026-04",
        employer_version(employer_id),
        [contribution_line_payload(base["participant"]["id"], 100.00, 400_000)],
    )
    api.create_contribution_report(payload, make_employer_headers(employer_id))

    rows, meta = validate_paginated(
        api.list_contribution_reports(ADMIN, params={"employer_id": employer_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == base["march_report"]["id"]

    assert read_withdrawal(base["assessment"]["id"])["status"] == "DRAFT"


def test_withdrawal_outranks_the_duplicate_work_period_rule(api):
    """PRD §2.8: "**Governance and segregation of duties.** The set of
    Taft-Hartley safety checks described throughout section 3: the contributing
    employer is not withdrawn (`ERR_EMPLOYER_WITHDRAWN`), a carried
    audit-settlement motion exists before an audit is finalized
    (`ERR_BOARD_APPROVAL_REQUIRED`), the finalizing administrator is not the
    audit's own auditor and the demanding administrator is not the certifying
    actuary (`ERR_SEGREGATION_OF_DUTIES`), the moving trustee does not vote on
    their own motion (`ERR_MOVER_CANNOT_VOTE`), the acting trustee's seat is
    active (`ERR_TRUSTEE_SEAT_INACTIVE`), the fund's governance posture is open
    before a motion may be moved (`ERR_FUND_GOVERNANCE_NOT_OPEN`) and not frozen
    before a demand may issue (`ERR_FUND_GOVERNANCE_FROZEN`), and the sister
    fund's reciprocity agreement is executed before a transfer may be accepted
    (`ERR_RECIPROCITY_AGREEMENT_NOT_EXECUTED`); all at HTTP 409."
    PRD §2.8: "**Uniqueness and chain rules.** Duplicate work period
    (`ERR_DUPLICATE_WORK_PERIOD`), invalid amendment target
    (`ERR_AMENDMENT_TARGET_INVALID`), duplicate vote (`ERR_DUPLICATE_VOTE`),
    empty report (`ERR_EMPTY_REPORT`), and audit round limit reached
    (`ERR_AUDIT_ROUND_LIMIT_REACHED`); all at HTTP 409, guarding contribution
    report filing, motion votes, and audit responses."
    PRD §2.8: "Checks are evaluated in the order below and the **first** failure
    wins; later checks are never reached."

    Design: Difficulty/priority_pair_validation_conflict/withdrawn_employer_safety_beats_duplicate_period_constraint
    """
    base = setup_withdrawn_employer_holding_a_live_report()
    employer_id = base["employer"]["id"]

    payload = create_contribution_report_payload(
        employer_id,
        "2026-03",
        employer_version(employer_id),
        [contribution_line_payload(base["participant"]["id"], 10.00, 40_000)],
    )

    response = api.create_contribution_report(
        payload, make_employer_headers(employer_id)
    )

    error_data = validate_error(response, ApiErrorId.ERR_EMPLOYER_WITHDRAWN.value)
    assert error_data["error_id"] != ApiErrorId.ERR_DUPLICATE_WORK_PERIOD.value
    assert response.status_code == 409


def test_the_doubly_invalid_filing_changes_nothing_at_all(api):
    """PRD §3.3: "An employer may hold at most one report per work period whose
    filing state is not `SUPERSEDED`, so filing a second report for a month that
    already has a live one, without naming an amendment target, is refused with
    `ERR_DUPLICATE_WORK_PERIOD`."
    PRD §3.9: "Opening an assessment moves the employer to `WITHDRAWN` — from
    `ACTIVE` or from `SUSPENDED` alike, so long as it is not already withdrawn —
    and from that moment the employer may file no further contribution reports."

    Design: Difficulty/priority_pair_validation_conflict/withdrawn_employer_safety_beats_duplicate_period_constraint
    """
    base = setup_withdrawn_employer_holding_a_live_report()
    employer_id = base["employer"]["id"]

    payload = create_contribution_report_payload(
        employer_id,
        "2026-03",
        employer_version(employer_id),
        [contribution_line_payload(base["participant"]["id"], 10.00, 40_000)],
    )
    api.create_contribution_report(payload, make_employer_headers(employer_id))

    assert read_employer(employer_id)["status"] == "WITHDRAWN"

    rows, meta = validate_paginated(
        api.list_contribution_reports(ADMIN, params={"employer_id": employer_id})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == base["report"]["id"]


def test_the_two_allocation_methods_diverge_on_byte_identical_employers(api):
    """PRD §3.9: "Under `PRESUMPTIVE`, the fraction is the sum of all five
    entries of the employer's `prior_year_contributions_cents` divided by the sum
    of all five entries of the fund's `pool_prior_year_contributions_cents`."
    PRD §3.9: "Under `ROLLING_FIVE`, the fund first finds the
    three-consecutive-year window that maximises the employer's own
    contributions: consider the three windows whose start index within the
    five-element array is 0, 1, or 2, sum the employer's
    `prior_year_contributions_cents` across each window's three years, and choose
    the window with the largest sum, breaking any tie in favour of the **lowest**
    start index, which is to say the earliest window; row identifiers are never
    consulted in that choice. The fraction is then the employer's sum over that
    window divided by the fund's `pool_prior_year_contributions_cents` summed
    over **the same index window** — not over the pool's own best window."
    PRD §3.9: "Fourth, the uncapped number of years is the net liability divided
    by the annual payment and rounded **up** to a whole number."

    Design: Corner/calculations/presumptive_and_rolling_five_allocations_diverge_on_identical_employer_data
    """
    set_clock()
    fund = create_fund(name="Method Divergence Fund", ein="36-5000001")
    twin_alpha = create_employer(fund["id"], legal_name="Twin Alpha", ein="36-5100001")
    twin_beta = create_employer(fund["id"], legal_name="Twin Beta", ein="36-5100002")

    presumptive = open_withdrawal(fund["id"], twin_alpha["id"], method="PRESUMPTIVE")
    rolling = open_withdrawal(fund["id"], twin_beta["id"], method="ROLLING_FIVE")

    assert presumptive["employer_share_fraction"] == 0.2500000000
    assert presumptive["raw_allocation_cents"] == 25_000_000
    assert presumptive["net_liability_cents"] == 25_000_000

    assert rolling["employer_share_fraction"] == 0.2750000000, (
        "the best three-year window starts at index 1"
    )
    assert rolling["raw_allocation_cents"] == 27_500_000
    assert rolling["net_liability_cents"] == 27_500_000

    assert presumptive["de_minimis_reduction_cents"] == 0
    assert rolling["de_minimis_reduction_cents"] == 0

    assert presumptive["annual_payment_cents"] == 5_448_300
    assert rolling["annual_payment_cents"] == 5_448_300, (
        "the base-unit window is chosen independently of the contribution window"
    )
    assert presumptive["schedule_years"] == 5
    assert rolling["schedule_years"] == 6


def test_certifying_a_certified_assessment_does_not_charge_the_pool_twice(api):
    """PRD §3.9: "Certification is the actuary's act and no one else's. The
    assessment must be in `DRAFT`, or the attempt is refused with
    `ERR_WITHDRAWAL_INVALID_STATE`."
    PRD §3.9: "Certifying stamps the acting actuary's opaque identity into
    `certified_by_user_id`, moves the assessment from `DRAFT` to `CERTIFIED`,
    adds the assessment's `net_liability_cents` to the fund's
    `allocated_uvb_cents`, recomputes `unallocated_uvb_cents` from the new
    allocated figure, and increments the fund's `version` by 1. This is the
    moment the pool actually shrinks."

    Design: Corner/state_machines/withdrawal_certify_twice_returns_withdrawal_invalid_state
    """
    set_clock()
    fund = create_fund(name="Double Certify Fund", ein="36-4000003")
    employer = create_employer(fund["id"])
    assessment = open_withdrawal(fund["id"], employer["id"])
    certify_withdrawal(assessment["id"])

    validate_error(
        api.certify_withdrawal_assessment(assessment["id"], ACTUARY),
        ApiErrorId.ERR_WITHDRAWAL_INVALID_STATE.value,
    )

    assert read_withdrawal(assessment["id"])["status"] == "CERTIFIED"
    fund_now = read_fund(fund["id"])
    assert fund_now["allocated_uvb_cents"] == 25_000_000
    assert fund_now["unallocated_uvb_cents"] == 75_000_000
    assert_fund_pool_split(fund_now)


def test_a_revised_review_returns_the_old_allocation_and_deletes_the_schedule(api):
    """PRD §3.9: "`REVISED` requires a `revised_total_uvb_cents` value that is
    present and at least 0, and rewinds the whole allocation: the assessment's
    current `net_liability_cents` is first subtracted back out of the fund's
    `allocated_uvb_cents` as an explicit compensating step, the fund's
    `total_uvb_cents` is replaced with `revised_total_uvb_cents` and
    `unallocated_uvb_cents` recomputed, and then the entire allocation and
    schedule are recomputed against the new pool — `employer_share_fraction`,
    `raw_allocation_cents`, `de_minimis_reduction_cents`, `net_liability_cents`,
    `annual_payment_cents`, `schedule_years`, `twenty_year_cap_applied` and
    `capped_liability_cents` all rewritten by the same rules and in the same
    order as at intake."
    PRD §3.9: "The new `net_liability_cents` is then added to the fund's
    `allocated_uvb_cents`, every installment of this assessment still in
    `SCHEDULED` is deleted, `demanded_on` returns to null, and the assessment
    returns to `CERTIFIED` so that a fresh demand must be issued against the
    revised figures."
    PRD §3.9: "Every installment except the last carries an `amount_cents` equal
    to `annual_payment_cents`; the final installment carries
    `capped_liability_cents` less `annual_payment_cents` multiplied by one fewer
    than `schedule_years`, which is how the schedule lands exactly on the capped
    total."

    Design: Corner/state_machines/withdrawal_review_revised_returns_uvb_to_pool_and_deletes_schedule
    """
    base = setup_assessment_under_review()
    assessment_id = base["assessment"]["id"]

    before = list_installments(assessment_id)
    assert len(before) == 5
    by_number = {row["installment_number"]: row for row in before}
    assert by_number[1]["due_date"] == "2026-05-31"
    assert by_number[1]["amount_cents"] == 5_448_300
    assert by_number[5]["amount_cents"] == 3_206_800
    assert read_fund(base["fund"]["id"])["allocated_uvb_cents"] == 25_000_000

    revised = validate_success(
        api.decide_withdrawal_review(
            assessment_id,
            {"decision": "REVISED", "revised_total_uvb_cents": 50_000_000},
            ADMIN,
        )
    )

    assert revised["status"] == "CERTIFIED"
    assert revised["demanded_on"] is None
    assert revised["raw_allocation_cents"] == 12_500_000
    assert revised["de_minimis_reduction_cents"] == 0
    assert revised["net_liability_cents"] == 12_500_000
    assert revised["annual_payment_cents"] == 5_448_300
    assert revised["schedule_years"] == 3
    assert revised["twenty_year_cap_applied"] is False
    assert revised["capped_liability_cents"] == 12_500_000

    fund = read_fund(base["fund"]["id"])
    assert fund["total_uvb_cents"] == 50_000_000
    assert fund["allocated_uvb_cents"] == 12_500_000
    assert fund["unallocated_uvb_cents"] == 37_500_000

    _rows, meta = validate_paginated(api.list_installments(assessment_id, ADMIN))
    assert meta["total_count"] == 0, "every SCHEDULED installment is deleted"


def test_an_empty_pool_and_a_zero_payment_base_each_refuse_the_assessment(api):
    """PRD §3.9: "There must, however, be something to allocate: an assessment
    opened while the fund's `unallocated_uvb_cents` stands at 0 or below is
    refused with `ERR_UVB_POOL_EXHAUSTED`."
    PRD §3.9: "Third, `annual_payment_cents` is that average multiplied by the
    employer's `contribution_rate_millicents_per_hour` and divided by 1,000 —
    millicents to cents — rounded half up to whole cents; if the result is 0
    there is no finite schedule and the request is refused with
    `ERR_NO_PAYMENT_BASE`."
    PRD §3.1: "`total_uvb_cents` defaults to 0 and holds the unfunded vested
    benefit pool available for allocation to withdrawing employers."

    Design: Corner/validations/withdrawal_intake_guards_reject_empty_pool_and_zero_payment_base
    """
    set_clock()
    empty_pool_fund = validate_success(
        api.create_fund(
            {
                "name": "Empty Pool Fund",
                "ein": "36-6000005",
                "interest_rate_annual_bps": 900,
                "ld_rate_bps": 2000,
                "ld_floor_cents": 5000,
                "grace_days": 15,
                "hours_per_coverage_month": 120,
                "bank_cap_hours": 480,
                "max_advance_coverage_months": 12,
                "eligibility_lag_months": 2,
                "accrual_method": "HOURS_BASED",
                "pool_prior_year_contributions_cents": [20_000_000] * 5,
            },
            ADMIN,
        ),
        201,
    )
    assert empty_pool_fund["total_uvb_cents"] == 0
    assert empty_pool_fund["unallocated_uvb_cents"] == 0

    pool_employer = create_employer(
        empty_pool_fund["id"], legal_name="Empty Pool Employer", ein="36-6100001"
    )

    funded_fund = create_fund(name="Zero Base Fund", ein="36-6000006")
    zero_base_employer = create_employer(
        funded_fund["id"],
        legal_name="No Hours Employer",
        ein="36-6100002",
        prior_year_base_units=[0, 0, 0, 0, 0],
    )

    validate_error(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(
                pool_employer["id"], fund_version(empty_pool_fund["id"])
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_UVB_POOL_EXHAUSTED.value,
    )

    validate_error(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(
                zero_base_employer["id"], fund_version(funded_fund["id"])
            ),
            ADMIN,
        ),
        ApiErrorId.ERR_NO_PAYMENT_BASE.value,
    )

    assert read_employer(pool_employer["id"])["status"] == "ACTIVE"
    assert read_employer(zero_base_employer["id"])["status"] == "ACTIVE"

    _rows, meta = validate_paginated(
        api.list_withdrawal_assessments(
            ADMIN, params={"employer_id": zero_base_employer["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_a_second_assessment_on_a_stale_fund_version_is_rejected(api):
    """PRD §2.7: "A `POST /withdrawal-assessments` request must carry
    `expected_fund_version`, holding the `version` of the fund as the client last
    observed it. If that value does not equal the fund's current `version`, the
    request is rejected with `ERR_STALE_FUND_VERSION` (HTTP 412)."
    PRD §3.9: "Opening an assessment moves the employer to `WITHDRAWN` — from
    `ACTIVE` or from `SUSPENDED` alike, so long as it is not already withdrawn —
    and from that moment the employer may file no further contribution reports.
    The fund's `version` increments by 1."

    Design: Corner/cross_cutting_layers/stale_fund_version_on_withdrawal_intake_is_rejected_with_412
    """
    set_clock()
    fund = create_fund(name="OCC Fund Version Fund", ein="36-9000002")
    first = create_employer(fund["id"], legal_name="First Withdrawer", ein="36-9100003")
    second = create_employer(fund["id"], legal_name="Second Withdrawer", ein="36-9100004")
    version_seen = fund_version(fund["id"])

    first_assessment = validate_success(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(first["id"], version_seen), ADMIN
        ),
        201,
    )

    validate_error(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(second["id"], version_seen), ADMIN
        ),
        ApiErrorId.ERR_STALE_FUND_VERSION.value,
    )
    assert read_employer(second["id"])["status"] == "ACTIVE"

    version_now = fund_version(fund["id"])
    assert version_now == version_seen + 1

    second_assessment = validate_success(
        api.create_withdrawal_assessment(
            create_withdrawal_assessment_payload(second["id"], version_now), ADMIN
        ),
        201,
    )
    assert read_employer(second["id"])["status"] == "WITHDRAWN"

    assert first_assessment["net_liability_cents"] == 25_000_000
    assert second_assessment["net_liability_cents"] == 25_000_000
    assert read_fund(fund["id"])["unallocated_uvb_cents"] == 100_000_000


def test_the_certifying_actuary_may_not_also_issue_the_demand(api):
    """PRD §3.9: "Demanding payment is the administrator's act, and it is fenced
    from the actuary's. The assessment must be `CERTIFIED`; the fund's
    `governance_posture` must not be `FROZEN`, and a demand issued by a board
    without both bargaining parties represented is refused with
    `ERR_FUND_GOVERNANCE_FROZEN`; the assessment's `annual_payment_cents` must be
    greater than 0; and the administrator issuing the demand must not be the same
    identity recorded in `certified_by_user_id`, an overlap being refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §3.9: "Certifying stamps the acting actuary's opaque identity into
    `certified_by_user_id`, moves the assessment from `DRAFT` to `CERTIFIED`,
    adds the assessment's `net_liability_cents` to the fund's
    `allocated_uvb_cents`, recomputes `unallocated_uvb_cents` from the new
    allocated figure, and increments the fund's `version` by 1."

    Design: Corner/rbac/actuary_who_certified_cannot_be_the_administrator_who_demands
    """
    set_clock()
    fund = create_fund(name="Segregation Fund", ein="36-7000005")
    create_trustee(fund["id"], "UNION", full_name="Union Trustee One")
    create_trustee(fund["id"], "EMPLOYER", full_name="Employer Trustee One")
    employer = create_employer(fund["id"])
    assessment = open_withdrawal(fund["id"], employer["id"])
    certified = certify_withdrawal(assessment["id"])

    assert certified["certified_by_user_id"] == ACTUARY_USER_ID

    validate_error(
        api.demand_withdrawal_assessment(
            assessment["id"], make_administrator_headers(ACTUARY_USER_ID)
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )

    refused = read_withdrawal(assessment["id"])
    assert refused["status"] == "CERTIFIED"
    _rows, meta = validate_paginated(api.list_installments(assessment["id"], ADMIN))
    assert meta["total_count"] == 0

    demanded = validate_success(
        api.demand_withdrawal_assessment(
            assessment["id"], make_administrator_headers(ADMIN_USER_ID)
        )
    )
    assert demanded["status"] == "DEMANDED"
    _minted, minted_meta = validate_paginated(
        api.list_installments(assessment["id"], ADMIN)
    )
    assert minted_meta["total_count"] == 5
