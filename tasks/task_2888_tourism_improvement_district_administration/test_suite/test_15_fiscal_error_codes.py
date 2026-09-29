"""The 404 vocabulary, and the fiscal refusals of the budget.

The first test pins the twelve-code not-found vocabulary against an empty
database, where nothing exists to be confused with anything else.  The rest walk
the money ceilings of the annual work plan: the two share bounds that bite at
approval, the variance allowance on an amendment, the funding-ratio floor and the
two arms of the lodging tax match.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_AMENDMENT_VARIANCE_EXCEEDED,
    ERR_ASSESSMENT_PERIOD_NOT_FOUND,
    ERR_CONTINGENCY_SHARE_EXCEEDED,
    ERR_DISPUTE_NOT_FOUND,
    ERR_FUNDING_RATIO_BELOW_MINIMUM,
    ERR_LODGING_BUSINESS_NOT_FOUND,
    ERR_LODGING_TAX_MATCH_CAP_EXCEEDED,
    ERR_LODGING_TAX_MATCH_EXHAUSTED,
    ERR_MARKETING_PROGRAM_NOT_FOUND,
    ERR_MARKETING_SHARE_BELOW_MINIMUM,
    ERR_PETITION_DRIVE_NOT_FOUND,
    ERR_PETITION_SIGNATURE_NOT_FOUND,
    ERR_ROOM_NIGHT_CLAIM_NOT_FOUND,
    ERR_TRANSPARENCY_RECORD_NOT_FOUND,
    ERR_WORK_PLAN_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_fields,
    assert_null_fields,
    assert_ratio_four_dp,
)
from test_helpers.test_users import (
    ADMIN,
    BOARD_MEMBER,
    BOARD_MEMBER_2,
    BOARD_MEMBER_USER_ID,
    DMO_LIAISON,
)


# --------------------------------------------------------------------------
# One not-found code per entity, on an empty database
# --------------------------------------------------------------------------
def test_each_entity_reports_its_own_not_found_code_on_an_empty_database(api):
    """Nine reads and two writes against identifiers that resolve to nothing report
    nine distinct 404 codes, and the two writes report existence rather than the
    state or separation rules they would otherwise have failed.

    PRD 2.8: "Existence - path identifiers are resolved left to right, and then body
    foreign keys in the order the fields are declared for that operation; the first
    unresolved reference decides which 404 is returned, from ERR_DISTRICT_NOT_FOUND,
    ERR_LODGING_BUSINESS_NOT_FOUND, ERR_PETITION_DRIVE_NOT_FOUND,
    ERR_PETITION_SIGNATURE_NOT_FOUND, ERR_ASSESSMENT_PERIOD_NOT_FOUND,
    ERR_ASSESSMENT_STATEMENT_NOT_FOUND, ERR_REMITTANCE_NOT_FOUND,
    ERR_WORK_PLAN_NOT_FOUND, ERR_MARKETING_PROGRAM_NOT_FOUND,
    ERR_ROOM_NIGHT_CLAIM_NOT_FOUND, ERR_TRANSPARENCY_RECORD_NOT_FOUND and
    ERR_DISPUTE_NOT_FOUND."

    Design: Corner/errors/unknown_ids_on_the_remaining_read_endpoints_each_return_their_own_not_found_code
    """
    absent = NON_EXISTENT_UUID
    reads = (
        (api.get_lodging_business(absent, headers=ADMIN), ERR_LODGING_BUSINESS_NOT_FOUND),
        (api.get_petition_drive(absent, headers=ADMIN), ERR_PETITION_DRIVE_NOT_FOUND),
        (api.get_petition_signature(absent, headers=ADMIN), ERR_PETITION_SIGNATURE_NOT_FOUND),
        (api.get_assessment_period(absent, headers=ADMIN), ERR_ASSESSMENT_PERIOD_NOT_FOUND),
        (api.get_work_plan(absent, headers=ADMIN), ERR_WORK_PLAN_NOT_FOUND),
        (api.get_marketing_program(absent, headers=ADMIN), ERR_MARKETING_PROGRAM_NOT_FOUND),
        (api.get_room_night_claim(absent, headers=ADMIN), ERR_ROOM_NIGHT_CLAIM_NOT_FOUND),
        (api.get_transparency_record(absent, headers=ADMIN), ERR_TRANSPARENCY_RECORD_NOT_FOUND),
        (api.get_dispute(absent, headers=ADMIN), ERR_DISPUTE_NOT_FOUND),
    )
    for response, error_id in reads:
        validate_error(response, error_id, expected_status=404)

    validate_error(
        api.generate_statements(absent, headers=ADMIN),
        ERR_ASSESSMENT_PERIOD_NOT_FOUND,
        expected_status=404,
    )
    validate_error(
        api.board_action(absent, f.board_action_payload("APPROVE"), headers=BOARD_MEMBER),
        ERR_WORK_PLAN_NOT_FOUND,
        expected_status=404,
    )

    codes = {error_id for _, error_id in reads}
    assert len(codes) == 9, (
        "the nine reads must report nine distinct codes, got %d: %r" % (len(codes), codes)
    )


# --------------------------------------------------------------------------
# The two share bounds that bite at approval
# --------------------------------------------------------------------------
_ONE_CENT_OVER_THE_CONTINGENCY_CAP = [
    f.expenditure_line("SALES_AND_MARKETING", 649999, "shoulder season campaign"),
    f.expenditure_line("ADMINISTRATION", 150000, "district staff and audit"),
    f.expenditure_line("CONTINGENCY_RESERVE", 100001, "storm season reserve"),
    f.expenditure_line("DESTINATION_EVENTS", 100000, "harbor festival"),
]
_ONE_CENT_UNDER_THE_MARKETING_FLOOR = [
    f.expenditure_line("SALES_AND_MARKETING", 599999, "shoulder season campaign"),
    f.expenditure_line("ADMINISTRATION", 150000, "district staff and audit"),
    f.expenditure_line("CONTINGENCY_RESERVE", 100000, "storm season reserve"),
    f.expenditure_line("DESTINATION_EVENTS", 150001, "harbor festival"),
]


def test_the_contingency_cap_and_the_marketing_floor_each_refuse_a_plan_by_one_cent(api):
    """Two plans of one million cents each are drafted and sponsored without
    complaint, and each is then refused at approval by a single cent: one for a
    reserve of 100,001 against a ceiling of 100,000, the other for a marketing line
    of 599,999 against a floor of 600,000.  The district holds no statement at all,
    so a funding ratio computed for either plan would be 0.0000, yet the reported
    code is the share bound in both cases.

    PRD 3.7: "The contingency cap is total_budget_cents multiplied by 0.10, rounded
    half up. The CONTINGENCY_RESERVE amount must be at or below it, and exceeding it
    yields ERR_CONTINGENCY_SHARE_EXCEEDED."

    PRD 3.7: "The marketing floor is total_budget_cents multiplied by 0.60, rounded
    half up. The SALES_AND_MARKETING amount must be at or above it, and falling
    short yields ERR_MARKETING_SHARE_BELOW_MINIMUM."

    Design: Corner/errors/the_contingency_cap_and_the_marketing_floor_both_refuse_a_plan_at_board_approval
    """
    ctx = fx.active_district(api)

    # A DRAFT plan may hold any category mix at all, so both non-compliant mixes
    # are accepted at creation.  The second plan carries a different fiscal year
    # because a district may not hold two live plans for the same year.
    over_reserve = fx.draft_work_plan(
        api, ctx, 2027, _ONE_CENT_OVER_THE_CONTINGENCY_CAP, key="wp_cont"
    )
    assert_fields(
        over_reserve,
        status="DRAFT",
        total_budget_cents=1000000,
        contingency_reserve_cents=100001,
        administration_cents=150000,
    )
    under_marketing = fx.draft_work_plan(
        api, ctx, 2028, _ONE_CENT_UNDER_THE_MARKETING_FLOOR, key="wp_mkt"
    )
    assert_fields(
        under_marketing,
        status="DRAFT",
        total_budget_cents=1000000,
        sales_and_marketing_cents=599999,
        administration_cents=150000,
    )

    for plan_key in ("wp_cont", "wp_mkt"):
        sponsored = fx.sponsor_work_plan(api, ctx, plan_key=plan_key)
        assert_fields(
            sponsored, status="BOARD_REVIEW", sponsor_user_id=BOARD_MEMBER_USER_ID
        )

    approve = f.board_action_payload("APPROVE", "put to the board")
    validate_error(
        api.board_action(ctx.wp_cont, approve, headers=BOARD_MEMBER_2),
        ERR_CONTINGENCY_SHARE_EXCEEDED,
        expected_status=409,
    )
    validate_error(
        api.board_action(ctx.wp_mkt, approve, headers=BOARD_MEMBER_2),
        ERR_MARKETING_SHARE_BELOW_MINIMUM,
        expected_status=409,
    )

    for plan_id in (ctx.wp_cont, ctx.wp_mkt):
        plan = validate_success(api.get_work_plan(plan_id, headers=ADMIN))
        assert_fields(plan, status="BOARD_REVIEW", revision_count=0)
        assert_null_fields(plan, "approver_user_id", "approved_at")


# --------------------------------------------------------------------------
# The variance allowance on an amendment
# --------------------------------------------------------------------------
_TWO_HUNDRED_SIXTY_THOUSAND_ABOVE_THE_BASELINE = [
    f.expenditure_line("SALES_AND_MARKETING", 800000, "expanded group sales"),
    f.expenditure_line("ADMINISTRATION", 180000, "district staff and audit"),
    f.expenditure_line("CONTINGENCY_RESERVE", 120000, "storm season reserve"),
    f.expenditure_line("DESTINATION_EVENTS", 160000, "harbor festival"),
]
_EXACTLY_THE_ALLOWANCE_ABOVE_THE_BASELINE = [
    f.expenditure_line("SALES_AND_MARKETING", 800000, "expanded group sales"),
    f.expenditure_line("ADMINISTRATION", 180000, "district staff and audit"),
    f.expenditure_line("CONTINGENCY_RESERVE", 120000, "storm season reserve"),
    f.expenditure_line("DESTINATION_EVENTS", 150000, "harbor festival"),
]


def test_an_amendment_is_measured_against_the_stored_total_and_admits_exactly_the_allowance(api):
    """The approved plan stands at one million cents, so the allowance is 250,000.
    A proposal 260,000 above it is refused and consumes nothing, and the identical
    expected version then carries a proposal exactly 250,000 above it to success.
    Both proposals clear every share bound and both keep the ratio above the floor,
    so only the variance ceiling can separate them.

    PRD 3.7: "the absolute difference between the proposed total and the plan's
    currently stored total_budget_cents must be at or below the variance allowance,
    which is that stored total multiplied by 0.25 and rounded half up".

    PRD 3.7: "The lines are replaced wholesale, every derived category total and
    total_budget_cents is recomputed, and revision_count increases by one."

    Design: Corner/errors/amendment_variance_is_measured_against_the_stored_total_and_admits_exactly_the_allowance
    """
    ctx = fx.statements_filed(api)
    approved = fx.approved_work_plan(api, ctx)
    assert_fields(
        approved,
        status="APPROVED",
        total_budget_cents=1000000,
        sales_and_marketing_cents=650000,
        assessment_revenue_forecast_cents=1164500,
        revision_count=0,
    )
    assert_ratio_four_dp(approved["funding_ratio"], 1.1645, "funding_ratio")
    baseline_version = approved["version"]

    validate_error(
        api.amend_work_plan(
            ctx.wp_id,
            f.work_plan_amendment_payload(
                baseline_version,
                _TWO_HUNDRED_SIXTY_THOUSAND_ABOVE_THE_BASELINE,
                "widen the autumn campaign",
            ),
            headers=ADMIN,
        ),
        ERR_AMENDMENT_VARIANCE_EXCEEDED,
        expected_status=409,
    )

    # The refusal wrote nothing, so the version that was rejected is still current.
    unchanged = validate_success(api.get_work_plan(ctx.wp_id, headers=ADMIN))
    assert_fields(
        unchanged,
        status="APPROVED",
        total_budget_cents=1000000,
        sales_and_marketing_cents=650000,
        destination_events_cents=100000,
        revision_count=0,
        version=baseline_version,
    )

    amended = validate_success(
        api.amend_work_plan(
            ctx.wp_id,
            f.work_plan_amendment_payload(
                baseline_version,
                _EXACTLY_THE_ALLOWANCE_ABOVE_THE_BASELINE,
                "widen the autumn campaign to the allowance",
            ),
            headers=ADMIN,
        )
    )
    assert_fields(
        amended,
        status="APPROVED",
        total_budget_cents=1250000,
        sales_and_marketing_cents=800000,
        administration_cents=180000,
        contingency_reserve_cents=120000,
        destination_events_cents=150000,
        capital_improvement_cents=0,
        revision_count=1,
        assessment_revenue_forecast_cents=1164500,
        version=baseline_version + 1,
    )
    assert_ratio_four_dp(amended["funding_ratio"], 0.9316, "funding_ratio")


# --------------------------------------------------------------------------
# The funding-ratio floor, read from the plan's own fiscal year
# --------------------------------------------------------------------------
def test_the_funded_fiscal_year_approves_and_the_unfunded_one_is_refused_on_the_same_district(api):
    """The district's only period is labelled FY2027-Q1, so the fiscal 2027 plan is
    approved at a ratio of 1.1645 while a fiscal 2028 plan of the identical
    compliant mix forecasts nothing and is refused at the floor.

    PRD 3.7: "assessment_revenue_forecast_cents is the sum of
    effective_assessment_cents over every assessment statement belonging to a period
    of the plan's district whose period_label begins with the characters FY followed
    by the plan's fiscal_year".

    PRD 3.7: "Finally the recomputed funding_ratio must be at least 0.9000, and
    falling short yields ERR_FUNDING_RATIO_BELOW_MINIMUM."

    Design: Corner/errors/the_funding_ratio_refuses_the_unfunded_fiscal_year_while_the_funded_one_approves
    """
    ctx = fx.statements_filed(api)
    fx.approved_work_plan(api, ctx)

    next_year = fx.draft_work_plan(api, ctx, 2028, key="wp28")
    assert_fields(
        next_year,
        fiscal_year=2028,
        total_budget_cents=1000000,
        sales_and_marketing_cents=650000,
        assessment_revenue_forecast_cents=0,
    )
    assert_ratio_four_dp(next_year["funding_ratio"], 0.0000, "funding_ratio")
    sponsored = fx.sponsor_work_plan(api, ctx, plan_key="wp28")
    assert_fields(sponsored, status="BOARD_REVIEW", total_budget_cents=1000000)

    validate_error(
        api.board_action(
            ctx.wp28, f.board_action_payload("APPROVE", "put to the board"), headers=BOARD_MEMBER_2
        ),
        ERR_FUNDING_RATIO_BELOW_MINIMUM,
        expected_status=409,
    )

    refused = validate_success(api.get_work_plan(ctx.wp28, headers=ADMIN))
    assert_fields(refused, status="BOARD_REVIEW")
    assert_null_fields(refused, "approver_user_id", "approved_at")

    funded = validate_success(api.get_work_plan(ctx.wp_id, headers=ADMIN))
    assert_fields(
        funded, status="APPROVED", assessment_revenue_forecast_cents=1164500
    )
    assert_ratio_four_dp(funded["funding_ratio"], 1.1645, "funding_ratio")

    plans, meta = validate_paginated(
        api.list_district_annual_work_plans(ctx.d_id, headers=ADMIN)
    )
    assert meta["total_count"] == 2, (
        "both plans must coexist on the district, got %r" % (meta,)
    )
    by_year = {plan["fiscal_year"]: plan["status"] for plan in plans}
    assert by_year == {2027: "APPROVED", 2028: "BOARD_REVIEW"}, (
        "the two live plans must hold different years and statuses, got %r" % (by_year,)
    )


# --------------------------------------------------------------------------
# The two arms of the lodging tax match
# --------------------------------------------------------------------------
def test_the_match_is_bounded_by_the_pool_and_by_half_the_approved_plan_total(api):
    """The approved plan of one million cents puts the statutory ceiling at 500,000,
    and the pool starts below it at 400,000.  The pool arm is reached first, from
    below: a program commits the whole pool, and lowering the pool underneath that
    commitment is refused outright.  Raising the pool to 900,000 makes the ceiling
    the binding arm, and one cent over it is refused while the exact ceiling is
    accepted.

    PRD 3.1: "if the new lodging_tax_match_pool_cents would fall below the district's
    already-committed lodging_tax_match_committed_cents, the coordination call is
    refused with ERR_LODGING_TAX_MATCH_EXHAUSTED".

    PRD 3.7: "The lodging tax match ceiling is total_budget_cents multiplied by 0.50,
    rounded half up. The district's lodging_tax_match_committed_cents must be at or
    below the smaller of that ceiling and the district's lodging_tax_match_pool_cents,
    and breaching either arm yields ERR_LODGING_TAX_MATCH_CAP_EXCEEDED."

    Design: Corner/errors/the_lodging_tax_match_is_bounded_by_the_pool_and_by_half_the_approved_plan_total
    """
    ctx = fx.statements_filed(api)
    plan = fx.approved_work_plan(api, ctx)
    assert_fields(plan, status="APPROVED", total_budget_cents=1000000,
                  sales_and_marketing_cents=650000)
    fx.execute_dmo_agreement(api, ctx)

    fx.create_program(
        api,
        ctx,
        key="mp_pool",
        name="Pool Funded Trade Show",
        channel="TRADE_SHOW",
        committed_cents=400000,
        lodging_tax_matched_cents=400000,
    )
    district = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        district,
        lodging_tax_match_pool_cents=400000,
        lodging_tax_match_committed_cents=400000,
    )
    version_before = district["version"]

    validate_error(
        api.record_dmo_coordination(
            ctx.d_id,
            f.dmo_coordination_payload(lodging_tax_match_pool_cents=300000),
            headers=ADMIN,
        ),
        ERR_LODGING_TAX_MATCH_EXHAUSTED,
        expected_status=409,
    )
    untouched = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        untouched,
        lodging_tax_match_pool_cents=400000,
        lodging_tax_match_committed_cents=400000,
        version=version_before,
    )

    widened = validate_success(
        api.record_dmo_coordination(
            ctx.d_id,
            f.dmo_coordination_payload(lodging_tax_match_pool_cents=900000),
            headers=ADMIN,
        )
    )
    assert_fields(
        widened,
        lodging_tax_match_pool_cents=900000,
        lodging_tax_match_committed_cents=400000,
        dmo_agreement_status="EXECUTED",
    )

    validate_error(
        api.create_marketing_program(
            f.marketing_program_payload(
                ctx.wp_id,
                name="One Cent Over The Ceiling",
                channel="PAID_SEARCH",
                committed_cents=100001,
                lodging_tax_matched_cents=100001,
            ),
            headers=DMO_LIAISON,
        ),
        ERR_LODGING_TAX_MATCH_CAP_EXCEEDED,
        expected_status=409,
    )

    fx.create_program(
        api,
        ctx,
        key="mp_cap",
        name="Exactly At The Ceiling",
        channel="PAID_SEARCH",
        committed_cents=100000,
        lodging_tax_matched_cents=100000,
    )
    at_ceiling = validate_success(api.get_district(ctx.d_id))
    assert_fields(
        at_ceiling,
        lodging_tax_match_pool_cents=900000,
        lodging_tax_match_committed_cents=500000,
    )

    funded_plan = validate_success(api.get_work_plan(ctx.wp_id, headers=ADMIN))
    assert_fields(funded_plan, committed_program_cents=500000)
    programs, meta = validate_paginated(
        api.list_plan_marketing_programs(ctx.wp_id, headers=ADMIN)
    )
    assert meta["total_count"] == 2, (
        "only the two accepted programs may exist, got %r" % (meta,)
    )
    assert {program["id"] for program in programs} == {ctx.mp_pool, ctx.mp_cap}, (
        "the refused program must not have been persisted; got %r"
        % ([program["id"] for program in programs],)
    )

    summary = validate_success(
        api.get_district_financial_summary(
            ctx.d_id, headers=ADMIN, params={"fiscal_year": 2027}
        )
    )
    assert_fields(summary, lodging_tax_match_committed_cents=500000)
