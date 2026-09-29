"""The refusals that stand between a well-formed request and the ledgers.

Each case here is a request that looks plausible and is turned away by exactly
one rung of the ladder, followed — where the rule permits — by the corrected
request that succeeds, proving the refusal wrote nothing.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_DEFAULT_UTC,
    INVESTOR_DELTA_USER_ID,
    REVIEWER_ANNUAL_USER_ID,
    SETUP_CLOCK,
    SPONSOR_BAYOU_USER_ID,
    SPONSOR_DELTA_USER_ID,
    add_project_company,
    add_sub_allocation,
    annual_test_payload,
    assert_cents,
    assert_instant,
    assert_pct,
    certification_number,
    certify_community_benefits,
    close_fund,
    create_cba,
    create_cde,
    create_cde_payload,
    create_census_tract_payload,
    create_fund,
    create_qalicb_payload,
    create_qei_payload,
    create_qlici_payload,
    create_tract,
    exercise_option_payload,
    file_job_report,
    get_success_data,
    issue_qei,
    make_agency_headers,
    make_qalicb_sponsor_headers,
    make_reviewer_headers,
    open_obligation_of,
    read_award,
    read_cba,
    read_cde,
    read_fund,
    read_obligation,
    read_qalicb,
    read_qei,
    read_qlici,
    read_tract,
    read_unwind,
    reinvestment_payload,
    repay_principal,
    set_clock,
    sign_award,
    setup_active_award,
    setup_certified_project_company,
    setup_deployed_investment,
    setup_funded_fund,
    setup_issued_investment,
    setup_open_option_window,
    setup_two_awards_one_entity,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_pagination_limit_of_zero_is_refused_while_one_hundred_is_honoured(api):
    """The page-size range is inclusive at both ends, and zero sits outside it.

    PRD: "`limit` caps the number of items returned; it defaults to 10, has a
    minimum of 1 and a maximum of 100."

    PRD: "A `limit` outside the range 1 through 100 inclusive, a non-integer
    `limit`, a negative `offset` or a non-integer `offset` is rejected with
    `ERR_INVALID_PAGINATION` (HTTP 400)."

    PRD: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/validations/pagination_limit_of_zero_returns_invalid_pagination
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    create_cde(
        api,
        certification_number=certification_number(111),
        service_area_scope="STATEWIDE",
    )

    for params in ({"limit": 0}, {"limit": 101}, {"offset": -1}):
        refused = api.list_cdes(make_agency_headers(), params=params)
        validate_error(refused, ApiErrorId.ERR_INVALID_PAGINATION.value, 400)

    rows, meta = validate_paginated(
        api.list_cdes(make_agency_headers(), params={"limit": 100, "offset": 0})
    )
    assert len(rows) == 1, "the one certified entity must still be listable"
    assert meta["limit"] == 100, "100 is the inclusive maximum, not an error"
    assert meta["offset"] == 0
    assert meta["total_count"] == 1
    assert meta["has_more"] is False


LOUISIANA_TRACT = {
    "tract_code": "22071000100",
    "state_code": "LA",
    "poverty_rate_pct": 31.00,
    "mfi_ratio_pct": 58.00,
    "unemployment_ratio": 1.20,
}
LOUISIANA_QALICB = {
    "legal_name": "Bayou Fabrication LLC",
    "state_code": "LA",
    "naics_code": "332710",
}
PLACEMENT_CENTS = 40_000_000


def test_a_business_outside_the_committed_service_area_cannot_be_funded(api):
    """The business is certified and its tract eligible; only the state is wrong.

    PRD: "Separately, the business's `state_code` must appear in the award's
    `service_area_state_codes`, or the deployment is refused with
    `ERR_OUTSIDE_SERVICE_AREA` — a check skipped altogether when the allocatee's
    `service_area_scope` is `NATIONAL`, since a nationally scoped entity has
    committed to no particular state list."

    PRD: "From `ISSUED`, a placement that leaves uninvested cash behind moves the
    investment to `DEPLOYING`, and one that consumes the last uninvested cent
    moves it straight to `FULLY_DEPLOYED`."

    Design: Corner/validations/a_qalicb_outside_the_award_service_area_blocks_the_qlici
    """
    scenario = setup_issued_investment(
        api, clock=SETUP_CLOCK, certification_suffix=112
    )
    assert scenario.award["service_area_state_codes"] == ["MS"]
    assert scenario.cde["service_area_scope"] == "MULTI_STATE"

    outsider = add_project_company(
        api,
        scenario,
        tract_overrides=LOUISIANA_TRACT,
        qalicb_overrides=LOUISIANA_QALICB,
        sponsor_user_id=SPONSOR_BAYOU_USER_ID,
    )
    assert outsider["eligibility_status"] == "CERTIFIED"
    assert outsider["state_code"] == "LA"
    assert read_tract(api, scenario.tracts[-1]["id"])["eligible_for_qlici"] is True

    refused = api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"], outsider["id"], principal_cents=PLACEMENT_CENTS
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_OUTSIDE_SERVICE_AREA.value, 422)

    inside = validate_success(
        api.create_qlici(
            create_qlici_payload(
                scenario.qei["id"],
                scenario.qalicb["id"],
                principal_cents=PLACEMENT_CENTS,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert inside["status"] == "DEPLOYED"
    assert_cents(
        inside["outstanding_principal_cents"],
        PLACEMENT_CENTS,
        "outstanding_principal_cents",
    )

    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 55_000_000, "uninvested_cash_cents")
    assert qei["deployment_status"] == "DEPLOYING"


def test_a_repeated_certification_number_or_tract_code_is_never_an_update(api):
    """The second registration is refused outright, and the first row is untouched.

    PRD: "`certification_number` is unique across community development entities
    and `tract_code` is unique across census tracts — otherwise
    `ERR_DUPLICATE_CERTIFICATION_NUMBER` or `ERR_DUPLICATE_TRACT_CODE`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule
    alone decides the response, and a rejected request persists nothing at all —
    no partial cascade, no counter movement, no version increment."

    PRD: "Because a tract is configuration rather than a live resource, it is
    never revised after registration; its adjacency edge remains readable as a
    filter on the register."

    Design: Corner/validations/duplicate_tract_code_and_duplicate_certification_number_both_return_409
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    cde = create_cde(
        api,
        certification_number=certification_number(113),
        service_area_scope="STATEWIDE",
    )
    tract = create_tract(api)

    refused_cde = api.create_cde(
        create_cde_payload(
            legal_name="Completely Different CDE Inc",
            certification_number=certification_number(113),
            service_area_scope="NATIONAL",
        ),
        make_agency_headers(),
    )
    validate_error(
        refused_cde, ApiErrorId.ERR_DUPLICATE_CERTIFICATION_NUMBER.value, 409
    )

    _, meta = validate_paginated(api.list_cdes(make_agency_headers()))
    assert meta["total_count"] == 1, "the refused registration created nothing"
    stored_cde = read_cde(api, cde["id"])
    assert stored_cde["legal_name"] == "Gulf Coast CDE"
    assert stored_cde["service_area_scope"] == "STATEWIDE"

    refused_tract = api.create_census_tract(
        create_census_tract_payload(
            tract_code="28049000100",
            state_code="LA",
            poverty_rate_pct=10.00,
            mfi_ratio_pct=95.00,
            unemployment_ratio=0.80,
        ),
        make_agency_headers(),
    )
    validate_error(refused_tract, ApiErrorId.ERR_DUPLICATE_TRACT_CODE.value, 409)

    stored_tract = read_tract(api, tract["id"])
    assert stored_tract["state_code"] == "MS"
    assert_pct(stored_tract["poverty_rate_pct"], 32.00, "poverty_rate_pct")
    assert_pct(stored_tract["mfi_ratio_pct"], 55.00, "mfi_ratio_pct")
    _, tract_meta = validate_paginated(api.list_census_tracts(make_agency_headers()))
    assert tract_meta["total_count"] == 1


# --- The two ceilings that bracket a redeployment ----------------------------

FIRST_PLACEMENT_CENTS = 85_000_000
SECOND_PLACEMENT_CENTS = 5_000_000
REPAYMENT_CLOCK = "2026-12-01T00:00:00.000Z"
REINVEST_BY_AT = "2027-12-01T00:00:00.000Z"
PAST_REINVESTMENT_DEADLINE_CLOCK = "2027-12-02T00:00:00.000Z"
INSIDE_BOTH_WINDOWS_CLOCK = "2026-12-15T00:00:00.000Z"
DEPLOYMENT_DEADLINE_AT = "2027-09-01T00:00:00.000Z"


def _two_placements_then_one_full_repayment(api, certification_suffix):
    """Class A repaid in full on 2026-12-01, leaving class B open to receive it."""
    scenario = setup_deployed_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=certification_suffix,
        qlici_overrides={"loan_class": "A", "principal_cents": FIRST_PLACEMENT_CENTS},
    )
    scenario.extras["qlici_b"] = add_sub_allocation(
        api,
        scenario,
        scenario.qalicb,
        loan_class="B",
        principal_cents=SECOND_PLACEMENT_CENTS,
    )
    set_clock(api, REPAYMENT_CLOCK)
    repay_principal(api, scenario.cde, scenario.qlici, FIRST_PLACEMENT_CENTS)
    scenario.obligation = open_obligation_of(api, scenario.qei["id"])
    return scenario


def test_redeploying_one_day_past_the_obligation_deadline_is_refused(api):
    """The deadline is inclusive, so 2027-12-02 is the first day too late.

    PRD: "**Hop two** returns the cash and opens the redeployment duty: the
    investment's `uninvested_cash_cents` rises by the repaid amount, and a
    reinvestment obligation row is created naming the investment through
    `qei_id` and the repaid sub-allocation through `source_qlici_id`, with
    `amount_cents` equal to the principal just returned, `reinvested_cents` at 0,
    `arose_at` stamped from the logical clock, `reinvest_by_at` set to that
    instant advanced by 365 days, `status` `OPEN`, and `satisfied_at` and
    `breached_at` both null."

    PRD: "The obligation must still be `OPEN`, the logical clock must be at or
    before its `reinvest_by_at` — a later attempt is
    `ERR_REINVESTMENT_DEADLINE_PASSED` — the amount must fit inside the
    investment's `uninvested_cash_cents`, or the answer is
    `ERR_INSUFFICIENT_UNINVESTED_CASH`, and the obligation's `reinvested_cents`
    plus the new amount may not exceed its `amount_cents`, or the answer is
    `ERR_REINVESTMENT_EXCEEDS_OBLIGATION`."

    PRD: "The reinvestment is inside the obligation's deadline, on reinvestment —
    otherwise `ERR_REINVESTMENT_DEADLINE_PASSED`."

    Design: Corner/validations/reinvesting_after_the_365_day_deadline_returns_reinvestment_deadline_passed
    """
    scenario = _two_placements_then_one_full_repayment(api, 114)
    obligation = scenario.obligation
    assert_cents(obligation["amount_cents"], FIRST_PLACEMENT_CENTS, "amount_cents")
    assert_instant(obligation["arose_at"], REPAYMENT_CLOCK, "arose_at")
    assert_instant(obligation["reinvest_by_at"], REINVEST_BY_AT, "reinvest_by_at")
    assert obligation["status"] == "OPEN"
    assert_instant(
        read_qei(api, scenario.qei["id"])["deployment_deadline_at"],
        DEPLOYMENT_DEADLINE_AT,
        "deployment_deadline_at",
    )

    set_clock(api, PAST_REINVESTMENT_DEADLINE_CLOCK)
    refused = api.reinvest(
        obligation["id"],
        reinvestment_payload(
            scenario.extras["qlici_b"]["id"], FIRST_PLACEMENT_CENTS
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_REINVESTMENT_DEADLINE_PASSED.value, 422)

    after = read_obligation(api, obligation["id"])
    assert_cents(after["reinvested_cents"], 0, "reinvested_cents")
    assert after["status"] == "OPEN", "the refused call does not itself breach it"
    target = read_qlici(api, scenario.extras["qlici_b"]["id"])
    assert_cents(
        target["outstanding_principal_cents"],
        SECOND_PLACEMENT_CENTS,
        "outstanding_principal_cents",
    )
    qei = read_qei(api, scenario.qei["id"])
    assert_cents(qei["uninvested_cash_cents"], 90_000_000, "uninvested_cash_cents")


def test_the_cash_ceiling_answers_before_the_obligation_ceiling(api):
    """One cent over the obligation names one error; one cent over the cash names another.

    PRD: "The requested placement fits inside the investment's uninvested cash,
    on sub-allocation deployment and on reinvestment — otherwise
    `ERR_INSUFFICIENT_UNINVESTED_CASH`."

    PRD: "A reinvestment does not exceed what the obligation still owes —
    otherwise `ERR_REINVESTMENT_EXCEEDS_OBLIGATION`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule
    alone decides the response, and a rejected request persists nothing at all —
    no partial cascade, no counter movement, no version increment."

    PRD: "On success the obligation's `reinvested_cents` rises by the amount, the
    target sub-allocation's `principal_cents` *and* its
    `outstanding_principal_cents` both rise by the same amount, and the
    investment's `uninvested_cash_cents` falls by it."

    PRD: "While the cumulative `reinvested_cents` remains strictly below the
    obligation's `amount_cents` the obligation stays `OPEN`; the moment the
    cumulative figure equals `amount_cents` exactly the obligation becomes
    `SATISFIED` with `satisfied_at` stamped from the logical clock."

    Design: Corner/validations/uninvested_cash_shortfall_outranks_the_reinvestment_ceiling
    """
    scenario = _two_placements_then_one_full_repayment(api, 115)
    obligation = scenario.obligation
    target_id = scenario.extras["qlici_b"]["id"]
    set_clock(api, INSIDE_BOTH_WINDOWS_CLOCK)

    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        90_000_000,
        "uninvested_cash_cents",
    )
    assert_cents(obligation["amount_cents"], 85_000_000, "amount_cents")
    assert_cents(obligation["reinvested_cents"], 0, "reinvested_cents")

    over_the_obligation = api.reinvest(
        obligation["id"],
        reinvestment_payload(target_id, 85_000_001),
        scenario.cde_headers,
    )
    validate_error(
        over_the_obligation, ApiErrorId.ERR_REINVESTMENT_EXCEEDS_OBLIGATION.value, 422
    )

    over_both = api.reinvest(
        obligation["id"],
        reinvestment_payload(target_id, 90_000_001),
        scenario.cde_headers,
    )
    validate_error(
        over_both, ApiErrorId.ERR_INSUFFICIENT_UNINVESTED_CASH.value, 422
    )

    still_open = read_obligation(api, obligation["id"])
    assert_cents(still_open["reinvested_cents"], 0, "reinvested_cents")
    assert still_open["status"] == "OPEN"

    satisfied = get_success_data(
        api.reinvest(
            obligation["id"],
            reinvestment_payload(target_id, 85_000_000),
            scenario.cde_headers,
        )
    )
    assert satisfied["status"] == "SATISFIED"
    assert_cents(satisfied["reinvested_cents"], 85_000_000, "reinvested_cents")
    assert_instant(
        satisfied["satisfied_at"], INSIDE_BOTH_WINDOWS_CLOCK, "satisfied_at"
    )

    target = read_qlici(api, target_id)
    assert_cents(
        target["outstanding_principal_cents"], 90_000_000, "outstanding_principal_cents"
    )
    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        5_000_000,
        "uninvested_cash_cents",
    )


# --- Ceilings and gates on the issuance itself -------------------------------

SMALL_AWARD_CENTS = 100_000_000
SPLIT_FUND_EQUITY_CENTS = 60_000_000
SPLIT_FUND_LEVERAGE_CENTS = 40_000_000


def _closed_fund(api, legal_name):
    """A fund carrying 60,000,000 of equity and 40,000,000 of leverage, closed."""
    fund = create_fund(
        api,
        INVESTOR_DELTA_USER_ID,
        legal_name=legal_name,
        equity_contribution_cents=SPLIT_FUND_EQUITY_CENTS,
        leverage_lender_name="Delta Bank",
        leverage_loan_principal_cents=SPLIT_FUND_LEVERAGE_CENTS,
        leverage_loan_rate_bps=450,
    )
    return close_fund(
        api,
        fund,
        INVESTOR_DELTA_USER_ID,
        equity_received_cents=SPLIT_FUND_EQUITY_CENTS,
        leverage_received_cents=SPLIT_FUND_LEVERAGE_CENTS,
    )


def test_the_second_investment_exhausts_an_authority_neither_request_exceeded(api):
    """The ceiling is the running ledger, not the size of any one request.

    PRD: "Finally, the gross amount must fit inside both the award's
    `remaining_authority_cents` and the fund's `capital_available_cents`;
    exceeding either is `ERR_INSUFFICIENT_ALLOCATION_AUTHORITY`, and the ledgers
    are left untouched."

    PRD: "On success the fund moves `FORMED` to `FUNDED`, stamps `closed_at` from
    the logical clock, records both received amounts, sets
    `leverage_loan_outstanding_cents` equal to the leverage received, sets
    `capital_available_cents` to the equity received plus the leverage received
    less anything already deployed, and increments the fund's `version`."

    Design: Corner/validations/qei_amount_above_remaining_authority_returns_insufficient_allocation_authority
    """
    scenario = setup_active_award(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=116,
        award_overrides={"allocation_amount_cents": SMALL_AWARD_CENTS},
    )
    fund_a = _closed_fund(api, "NMTC Fund A LLC")
    fund_b = _closed_fund(api, "NMTC Fund B LLC")
    assert_cents(
        fund_a["capital_available_cents"], 100_000_000, "capital_available_cents"
    )
    assert_cents(
        fund_b["capital_available_cents"], 100_000_000, "capital_available_cents"
    )

    first = issue_qei(
        api,
        scenario.cde,
        scenario.award,
        fund_a,
        qei_amount_cents=SPLIT_FUND_EQUITY_CENTS,
    )
    award = read_award(api, scenario.award["id"])
    assert_cents(
        award["remaining_authority_cents"], 40_000_000, "remaining_authority_cents"
    )
    assert award["issued_qei_count"] == 1

    refused = api.create_qei(
        create_qei_payload(
            award["id"],
            fund_b["id"],
            award["version"],
            qei_amount_cents=SPLIT_FUND_EQUITY_CENTS,
        ),
        scenario.cde_headers,
    )
    validate_error(
        refused, ApiErrorId.ERR_INSUFFICIENT_ALLOCATION_AUTHORITY.value, 422
    )

    second = validate_success(
        api.create_qei(
            create_qei_payload(
                award["id"],
                fund_b["id"],
                award["version"],
                qei_amount_cents=40_000_000,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    award = read_award(api, scenario.award["id"])
    assert_cents(award["remaining_authority_cents"], 0, "remaining_authority_cents")
    assert award["issued_qei_count"] == 2
    assert_cents(first["qei_amount_cents"], 60_000_000, "qei_amount_cents")
    assert_cents(second["qei_amount_cents"], 40_000_000, "qei_amount_cents")
    assert_cents(
        read_fund(api, fund_b["id"])["deployed_to_qei_cents"],
        40_000_000,
        "deployed_to_qei_cents",
    )


def test_a_fund_that_declared_its_capital_but_never_closed_cannot_invest(api):
    """The paper capital stack is not received money, and issuance reads the state.

    PRD: "The backing fund must be in `FUNDED` — its equity and leverage proceeds
    both received and closing run — or the request is refused with
    `ERR_FUND_NOT_FUNDED`."

    PRD: "Rules are evaluated in ascending priority, the first violated rule
    alone decides the response, and a rejected request persists nothing at all —
    no partial cascade, no counter movement, no version increment."

    PRD: "The `net_deployable_cents` are the gross amount less those permitted
    fees, and `uninvested_cash_cents` opens at exactly that net figure."

    Design: Corner/validations/issuing_a_qei_from_a_formed_fund_returns_fund_not_funded
    """
    scenario = setup_active_award(
        api, clock=SETUP_CLOCK, certification_suffix=117
    )
    setup_funded_fund(api, scenario, close=False)
    assert scenario.fund["status"] == "FORMED"
    signed_version = scenario.award["version"]

    refused = api.create_qei(
        create_qei_payload(
            scenario.award["id"],
            scenario.fund["id"],
            signed_version,
            qei_amount_cents=100_000_000,
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_FUND_NOT_FUNDED.value, 422)

    award = read_award(api, scenario.award["id"])
    assert_cents(
        award["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )
    assert award["version"] == signed_version, "a refused write never bumps the version"

    close_fund(
        api,
        scenario.fund,
        INVESTOR_DELTA_USER_ID,
        equity_received_cents=65_000_000,
        leverage_received_cents=35_000_000,
    )
    qei = validate_success(
        api.create_qei(
            create_qei_payload(
                scenario.award["id"],
                scenario.fund["id"],
                signed_version,
                qei_amount_cents=100_000_000,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert_cents(qei["qei_amount_cents"], 100_000_000, "qei_amount_cents")
    assert_cents(qei["net_deployable_cents"], 95_000_000, "net_deployable_cents")

    fund = read_fund(api, scenario.fund["id"])
    assert fund["status"] == "QEI_MADE"
    assert_cents(fund["deployed_to_qei_cents"], 100_000_000, "deployed_to_qei_cents")


def test_an_agreement_bound_to_the_entitys_other_award_does_not_count(api):
    """The commitment must bind this business to the award paying for the money.

    PRD: "There must in fact *be* an agreement binding that business to the same
    award as the funding investment; a business with no such agreement is refused
    with `ERR_CBA_MISSING`, which is what forces the community-outcome commitment
    to exist before the money moves rather than after."

    PRD: "The percentage is 100 multiplied by the sum of
    `outstanding_principal_cents` across that qualifying set, divided by the
    investment's gross `qei_amount_cents` less its `permitted_fees_cents`, and
    rounded half-up to 2 decimal places."

    Design: Corner/validations/deploying_to_a_qalicb_without_an_agreement_for_this_award_returns_cba_missing
    """
    scenario = setup_two_awards_one_entity(
        api, clock=SETUP_CLOCK, certification_suffix=118
    )
    second_award = scenario.extras["second_award"]
    assert second_award["award_year"] == 2027
    assert second_award["lifecycle_status"] == "ACTIVE"

    setup_certified_project_company(api, scenario)
    other_agreement = create_cba(
        api, scenario.cde, scenario.qalicb, second_award
    )
    setup_funded_fund(api, scenario)
    award_2026 = read_award(api, scenario.award["id"])
    qei = issue_qei(
        api,
        scenario.cde,
        award_2026,
        scenario.fund,
        qei_amount_cents=100_000_000,
    )

    refused = api.create_qlici(
        create_qlici_payload(
            qei["id"], scenario.qalicb["id"], principal_cents=85_000_000
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CBA_MISSING.value, 422)
    assert read_cba(api, other_agreement["id"])["status"] == "ACTIVE"

    this_agreement = create_cba(api, scenario.cde, scenario.qalicb, award_2026)
    assert this_agreement["allocation_award_id"] == award_2026["id"]
    assert this_agreement["status"] == "ACTIVE"

    placed = validate_success(
        api.create_qlici(
            create_qlici_payload(
                qei["id"], scenario.qalicb["id"], principal_cents=85_000_000
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert placed["status"] == "DEPLOYED"

    funded = read_qei(api, qei["id"])
    assert_cents(funded["uninvested_cash_cents"], 10_000_000, "uninvested_cash_cents")
    assert_pct(
        funded["substantially_all_pct_direct"], 89.47, "substantially_all_pct_direct"
    )


REPORT_PERIOD_START_AT = "2026-09-01T00:00:00.000Z"
REPORT_PERIOD_END_AT = "2027-08-31T00:00:00.000Z"
CERTIFICATION_CLOCK = "2027-09-01T00:00:00.000Z"


def test_the_breached_agreement_blocks_the_next_placement_not_the_business(api):
    """Eighteen qualifying heads against a target of twenty-five breaches the deal.

    PRD: "Under `HEADCOUNT`, the `achieved_fte` is the sum of
    `qualifying_headcount` across the wage-passing reports, and is therefore a
    whole number of people."

    PRD: "The `local_hire_pct` spans **every** report in the window, wage-failing
    ones included: it is 100 multiplied by the sum of `local_hires` across all
    those reports, divided by the sum of their `headcount`, rounded half-up to 2
    decimal places, and it is 0.00 when that total headcount is 0."

    PRD: "Anything else — a compliance percentage below 80.00, or a local-hire
    percentage short of target at any compliance level — is `SHORTFALL`."

    PRD: "A `SHORTFALL` moves the agreement to `BREACHED` with `breached_at`
    stamped from the logical clock."

    PRD: "Otherwise, if the award has at least two investments whose
    `compliance_status` is `AT_RISK`, or at least one community benefits agreement
    in `BREACHED`, the posture is `RESTRICTED`, which bars new investment issuance
    while still permitting sub-allocations from investments already issued."

    PRD: "Its community benefits agreement must not be `BREACHED`, or the answer
    is `ERR_CBA_BREACHED`."

    Design: Corner/validations/a_breached_agreement_blocks_further_deployment_to_that_qalicb
    """
    scenario = setup_deployed_investment(
        api,
        clock=SETUP_CLOCK,
        certification_suffix=119,
        qlici_overrides={"principal_cents": 30_000_000},
    )
    assert scenario.cba["measurement_basis"] == "HEADCOUNT"
    assert scenario.cba["target_fte_count"] == 25

    set_clock(api, CERTIFICATION_CLOCK)
    report = file_job_report(
        api,
        scenario.cba,
        REPORT_PERIOD_START_AT,
        REPORT_PERIOD_END_AT,
        headcount=20,
        qualifying_headcount=18,
        local_hires=12,
        avg_hourly_wage_cents=1950,
    )
    assert report["wage_floor_met"] is True

    certification = certify_community_benefits(
        api,
        scenario.cba,
        1,
        REPORT_PERIOD_START_AT,
        REPORT_PERIOD_END_AT,
        reviewer_user_id=REVIEWER_ANNUAL_USER_ID,
    )
    assert certification["measurement_basis"] == "HEADCOUNT"
    assert certification["report_count"] == 1
    assert certification["excluded_wage_failing_report_count"] == 0
    assert certification["achieved_fte"] == 18
    assert_pct(certification["compliance_pct"], 72.00, "compliance_pct")
    assert_pct(certification["local_hire_pct"], 60.00, "local_hire_pct")
    assert certification["classification"] == "SHORTFALL"
    assert certification["resulting_status"] == "BREACHED"

    agreement = read_cba(api, scenario.cba["id"])
    assert agreement["status"] == "BREACHED"
    assert_instant(agreement["breached_at"], CERTIFICATION_CLOCK, "breached_at")

    award = read_award(api, scenario.award["id"])
    assert award["cba_breach_count"] == 1
    assert award["compliance_posture"] == "RESTRICTED"

    refused = api.create_qlici(
        create_qlici_payload(
            scenario.qei["id"], scenario.qalicb["id"], principal_cents=10_000_000
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_CBA_BREACHED.value, 422)

    assert read_qalicb(api, scenario.qalicb["id"])["eligibility_status"] == "CERTIFIED"
    assert_cents(
        read_qei(api, scenario.qei["id"])["uninvested_cash_cents"],
        65_000_000,
        "uninvested_cash_cents",
    )


def test_an_announced_award_refuses_the_investment_its_authority_could_fund(api):
    """Full authority, a funded fund, a current version — and still no signature.

    PRD: "The award must be `ACTIVE`, its allocatee still `CERTIFIED`, and its
    posture neither `RESTRICTED` nor `FROZEN`."

    PRD: "If that value does not equal the award's current `version`, the request
    is rejected with `ERR_STALE_AWARD_VERSION` (HTTP 412) and nothing is
    persisted."

    PRD: "Rules are evaluated in ascending priority, the first violated rule
    alone decides the response, and a rejected request persists nothing at all —
    no partial cascade, no counter movement, no version increment."

    Design: Corner/validations/issuing_a_qei_before_the_agreement_is_signed_returns_award_not_active
    """
    scenario = setup_active_award(
        api, clock=SETUP_CLOCK, certification_suffix=120, sign=False
    )
    assert scenario.award["lifecycle_status"] == "ANNOUNCED"
    announced_version = scenario.award["version"]
    setup_funded_fund(api, scenario)
    assert_cents(
        scenario.fund["capital_available_cents"],
        100_000_000,
        "capital_available_cents",
    )

    refused = api.create_qei(
        create_qei_payload(
            scenario.award["id"],
            scenario.fund["id"],
            announced_version,
            qei_amount_cents=100_000_000,
        ),
        scenario.cde_headers,
    )
    validate_error(refused, ApiErrorId.ERR_AWARD_NOT_ACTIVE.value, 409)

    award = read_award(api, scenario.award["id"])
    assert award["issued_qei_count"] == 0
    assert_cents(
        award["remaining_authority_cents"], 5_000_000_000, "remaining_authority_cents"
    )
    assert award["version"] == announced_version

    signed = sign_award(api, scenario.cde, award)
    qei = validate_success(
        api.create_qei(
            create_qei_payload(
                signed["id"],
                scenario.fund["id"],
                signed["version"],
                qei_amount_cents=100_000_000,
            ),
            scenario.cde_headers,
        ),
        201,
    )
    assert qei["deployment_status"] == "ISSUED"

    award = read_award(api, scenario.award["id"])
    assert award["lifecycle_status"] == "ACTIVE"
    assert award["issued_qei_count"] == 1
    assert_cents(
        award["remaining_authority_cents"], 4_900_000_000, "remaining_authority_cents"
    )


YEAR_ONE_WINDOW_END_CLOCK = "2027-09-01T00:00:00.000Z"


def test_skipping_a_year_and_repeating_a_year_are_caught_by_different_rungs(api):
    """Year two is a skip; year one twice is a window collision.

    PRD: "Years may not be skipped: the requested year must be no greater than
    the investment's `compliance_years_completed` plus one, and a request for a
    later year than the next one due is `ERR_TEST_SEQUENCE_INVALID`."

    PRD: "A request naming a year that has *already* been tested passes that rung
    deliberately and is caught one rung lower by the window check: no two annual
    tests of the same investment may cover overlapping windows, and a repeat is
    `ERR_TEST_WINDOW_OVERLAP`."

    PRD: "The test copies the award's `substantially_all_method` into its own
    `governing_method`, and sets `governing_pct` to `measured_pct_direct` when
    that method is `DIRECT_TRACING` and to `measured_pct_aggregate` when it is
    `AGGREGATE_BALANCE`."

    Design: Corner/validations/skipping_a_compliance_year_and_re_testing_a_tested_year_return_different_errors
    """
    scenario = setup_deployed_investment(
        api, clock=SETUP_CLOCK, certification_suffix=121
    )
    assert scenario.award["substantially_all_method"] == "DIRECT_TRACING"
    assert scenario.qei["compliance_years_completed"] == 0
    reviewer = make_reviewer_headers(REVIEWER_ANNUAL_USER_ID)
    set_clock(api, YEAR_ONE_WINDOW_END_CLOCK)

    skipped = api.run_annual_test(
        scenario.qei["id"], annual_test_payload(2), reviewer
    )
    validate_error(skipped, ApiErrorId.ERR_TEST_SEQUENCE_INVALID.value, 409)

    first = get_success_data(
        api.run_annual_test(scenario.qei["id"], annual_test_payload(1), reviewer)
    )
    assert first["result"] == "PASS"
    assert_pct(first["measured_pct_direct"], 89.47, "measured_pct_direct")
    assert_pct(first["governing_pct"], 89.47, "governing_pct")
    assert first["governing_method"] == "DIRECT_TRACING"

    repeated = api.run_annual_test(
        scenario.qei["id"], annual_test_payload(1), reviewer
    )
    validate_error(repeated, ApiErrorId.ERR_TEST_WINDOW_OVERLAP.value, 409)

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_years_completed"] == 1
    assert qei["compliance_status"] == "COMPLIANT"
    rows, meta = validate_paginated(
        api.list_annual_tests(scenario.qei["id"], reviewer)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1


OPTION_WINDOW_OPEN_AT = "2033-08-30T00:00:00.000Z"
OPTION_WINDOW_CLOSE_AT = "2033-11-28T00:00:00.000Z"


def test_an_exercise_at_the_closing_instant_is_already_too_late(api):
    """The option window's upper bound is exclusive, so the close instant refuses.

    PRD: "The `option_window_open_at` is the investment's `issued_at` advanced by
    2555 days — seven years of 365 days each — and the `option_window_close_at`
    is 90 days after that, so the window's lower bound is inclusive and its upper
    bound exclusive."

    PRD: "Both branches require the row to be in `OPTION_WINDOW_OPEN`, require the
    investment's `compliance_status` to be `COMPLIANT`, and require the logical
    clock to be at or after `option_window_open_at` and strictly before
    `option_window_close_at` — outside that window the answer is
    `ERR_OPTION_WINDOW_CLOSED`."

    PRD: "The row opens in `status` `OPTION_WINDOW_OPEN` with
    `exercised_option_type`, `exercised_at`, `settlement_reference` and
    `settled_at` all null and `settlement_amount_cents` at 0."

    PRD: "From `ISSUED`, a placement that leaves uninvested cash behind moves the
    investment to `DEPLOYING`, and one that consumes the last uninvested cent
    moves it straight to `FULLY_DEPLOYED`."

    Design: Corner/validations/exercising_an_option_after_the_ninety_day_window_returns_option_window_closed
    """
    scenario = setup_open_option_window(
        api,
        call_holder_user_id=SPONSOR_DELTA_USER_ID,
        certification_suffix=122,
    )
    unwind = scenario.unwind
    assert_instant(
        unwind["option_window_open_at"], OPTION_WINDOW_OPEN_AT, "option_window_open_at"
    )
    assert_instant(
        unwind["option_window_close_at"],
        OPTION_WINDOW_CLOSE_AT,
        "option_window_close_at",
    )
    assert unwind["status"] == "OPTION_WINDOW_OPEN"
    before = read_qei(api, scenario.qei["id"])

    set_clock(api, OPTION_WINDOW_CLOSE_AT)
    refused = api.exercise_option(
        unwind["id"],
        exercise_option_payload("CALL"),
        make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
    )
    validate_error(refused, ApiErrorId.ERR_OPTION_WINDOW_CLOSED.value, 422)

    after = read_unwind(api, unwind["id"])
    assert after["status"] == "OPTION_WINDOW_OPEN"
    assert after["exercised_option_type"] is None
    assert after["exercised_at"] is None
    assert_cents(after["settlement_amount_cents"], 0, "settlement_amount_cents")
    assert_cents(after["put_price_cents"], 100_000, "put_price_cents")
    assert_cents(after["call_price_cents"], 1_500_000, "call_price_cents")

    qei = read_qei(api, scenario.qei["id"])
    assert qei["compliance_status"] == "COMPLIANT"
    assert qei["deployment_status"] == "DEPLOYING", (
        "85,000,000 of a 95,000,000 net leaves uninvested cash behind"
    )
    assert qei["deployment_status"] == before["deployment_status"]


INELIGIBLE_TRACT = {
    "tract_code": "28049000600",
    "state_code": "MS",
    "poverty_rate_pct": 12.00,
    "mfi_ratio_pct": 95.00,
    "unemployment_ratio": 0.80,
}
SEVERE_TRACT = {
    "tract_code": "28049000100",
    "state_code": "MS",
    "poverty_rate_pct": 32.00,
    "mfi_ratio_pct": 55.00,
    "unemployment_ratio": 1.80,
}


def test_an_ineligible_tract_stops_the_business_and_the_neighbour_that_names_it(api):
    """The location gate bites at registration, twice over.

    PRD: "The statutory low-income-community test is a disjunction of two prongs:
    `is_low_income_community` is true when the `poverty_rate_pct` is at least
    20.00, or when the `mfi_ratio_pct` is at most 80.00."

    PRD: "A tract that is not `eligible_for_qlici` is `INELIGIBLE` regardless of
    its statistics."

    PRD: "The tract named must be `eligible_for_qlici`; a business whose principal
    location does not qualify is refused with `ERR_TRACT_NOT_LIC_ELIGIBLE`."

    PRD: "The named adjoining tract must itself have `is_low_income_community`
    true; a contiguity claim that points at a tract which does not qualify on its
    own statistics is refused with `ERR_TRACT_NOT_LIC_ELIGIBLE`."

    PRD: "A new business starts with `eligibility_status` `PENDING`,
    `last_certified_at` and `latest_test_result` both null,
    `consecutive_failed_test_count` at 0, and `funding_qlici_count` at 0 — that
    counter tracks how many of its sub-allocations have a `status` other than
    `REPAID`."

    Design: Corner/validations/registering_a_qalicb_in_an_ineligible_tract_returns_tract_not_lic_eligible
    """
    set_clock(api, CLOCK_DEFAULT_UTC)
    bad = validate_success(
        api.create_census_tract(
            create_census_tract_payload(**INELIGIBLE_TRACT), make_agency_headers()
        ),
        201,
    )
    good = validate_success(
        api.create_census_tract(
            create_census_tract_payload(**SEVERE_TRACT), make_agency_headers()
        ),
        201,
    )
    assert bad["is_low_income_community"] is False
    assert bad["qualifies_by_contiguity"] is False
    assert bad["eligible_for_qlici"] is False
    assert bad["distress_tier"] == "INELIGIBLE"

    refused_business = api.create_qalicb(
        create_qalicb_payload(
            bad["id"],
            legal_name="Suburban Retail LLC",
            state_code="MS",
            naics_code="441110",
        ),
        make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
    )
    validate_error(
        refused_business, ApiErrorId.ERR_TRACT_NOT_LIC_ELIGIBLE.value, 422
    )

    refused_neighbour = api.create_census_tract(
        create_census_tract_payload(
            contiguous_lic_tract_id=bad["id"],
            tract_code="28049000700",
            state_code="MS",
            poverty_rate_pct=16.00,
            mfi_ratio_pct=85.00,
            unemployment_ratio=1.00,
        ),
        make_agency_headers(),
    )
    validate_error(
        refused_neighbour, ApiErrorId.ERR_TRACT_NOT_LIC_ELIGIBLE.value, 422
    )

    accepted = validate_success(
        api.create_qalicb(
            create_qalicb_payload(
                good["id"],
                legal_name="Delta Foods LLC",
                state_code="MS",
                naics_code="311412",
            ),
            make_qalicb_sponsor_headers(SPONSOR_DELTA_USER_ID),
        ),
        201,
    )
    assert accepted["eligibility_status"] == "PENDING"
    assert accepted["funding_qlici_count"] == 0

    _, meta = validate_paginated(api.list_census_tracts(make_agency_headers()))
    assert meta["total_count"] == 2, "the refused neighbour was never created"
