"""Validation precedence and boundary conditions across the 32-step ladder."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_null, assert_same_instant


def test_duplicate_jurisdiction_code_rate_plan_name_and_firm_name_are_refused(api):
    """All three globally unique reference-data keys report their own 409.

    PRD: "A duplicate jurisdiction code is `ERR_DUPLICATE_JURISDICTION_CODE`, a
    duplicate plan name is `ERR_DUPLICATE_RATE_PLAN_NAME` and a duplicate firm
    name is `ERR_DUPLICATE_PANEL_FIRM_NAME`, all HTTP 409."

    Design: Corner/validations/duplicate_jurisdiction_code_rate_plan_name_and_firm_name_are_refused
    """
    S.create_jurisdiction(api, "TX")
    plan = S.create_draft_rate_plan(api)
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )

    dup_code = api.create_jurisdiction(
        F.jurisdiction(
            "TX",
            name="Texas Republic",
            hazard_tier=T.HAZARD_TIER_4,
            admin_agency_name="Some Other Agency",
            pre_suit_window_days=300,
            wage_hour_multiplier=1.90,
            class_action_propensity_pct=55.00,
        ),
        U.ADMIN,
    )
    code_body = validate_error(dup_code, E.ERR_DUPLICATE_JURISDICTION_CODE, 409)
    assert dup_code.json()["response_type"] == "error"
    assert code_body["message"].strip() != ""

    dup_plan = api.create_rate_plan(
        F.rate_plan(
            name="EPLI Standard 2026",
            base_rate_per_employee_cents=99999,
            min_premium_cents=100000,
            wage_hour_sublimit_pct=0.10,
            third_party_sublimit_pct=0.10,
        ),
        U.ADMIN,
    )
    plan_body = validate_error(dup_plan, E.ERR_DUPLICATE_RATE_PLAN_NAME, 409)
    assert dup_plan.json()["response_type"] == "error"
    assert plan_body["message"].strip() != ""

    dup_firm = api.create_panel_firm(
        F.panel_firm(
            name="Ashford & Vance LLP",
            tier=T.TIER_LOCAL,
            jurisdiction_codes=["TX"],
            partner_rate_cents_per_hour=10000,
            associate_rate_cents_per_hour=9000,
            paralegal_rate_cents_per_hour=8000,
            capacity_open_matters=1,
        ),
        U.ADMIN,
    )
    firm_body = validate_error(dup_firm, E.ERR_DUPLICATE_PANEL_FIRM_NAME, 409)
    assert dup_firm.json()["response_type"] == "error"
    assert firm_body["message"].strip() != ""

    kept_plan = get_success_data(api.get_rate_plan(plan["id"], U.ADMIN))
    assert kept_plan["base_rate_per_employee_cents"] == 41750
    kept_firm = get_success_data(api.get_panel_firm(firm["id"], U.ADMIN))
    assert_fields(kept_firm, {"tier": T.TIER_NATIONAL, "capacity_open_matters": 3})


def test_headcount_allocation_must_sum_and_include_the_primary_jurisdiction(api):
    """Both allocation invariants are enforced at registration and at revision.

    PRD: "the `headcount` values must sum to exactly `total_headcount`, and
    `primary_jurisdiction_code` must itself appear among the array's codes. A
    violation of either is `ERR_HEADCOUNT_ALLOCATION_MISMATCH` (HTTP 422)."

    Design: Corner/validations/headcount_allocation_must_sum_and_include_the_primary_jurisdiction
    """
    S.create_jurisdictions(api, ["TX", "CA"])
    applicant = S.create_applicant(
        api,
        legal_name="Harbor Lane Retail LLC",
        total_headcount=100,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 60}, {"code": "CA", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )

    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Sumless Holdings LLC",
                total_headcount=100,
                prior_year_separations=0,
                jurisdiction_headcounts=[
                    {"code": "TX", "headcount": 40},
                    {"code": "CA", "headcount": 30},
                ],
                primary_jurisdiction_code="TX",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_HEADCOUNT_ALLOCATION_MISMATCH,
        422,
    )
    validate_error(
        api.create_applicant(
            F.applicant(
                legal_name="Absentee Primary LLC",
                total_headcount=100,
                prior_year_separations=0,
                jurisdiction_headcounts=[{"code": "TX", "headcount": 100}],
                primary_jurisdiction_code="CA",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_HEADCOUNT_ALLOCATION_MISMATCH,
        422,
    )
    validate_error(
        api.patch_applicant(
            applicant["id"],
            {
                "jurisdiction_headcounts": [
                    {"code": "TX", "headcount": 60},
                    {"code": "CA", "headcount": 30},
                ]
            },
            U.UNDERWRITER,
        ),
        E.ERR_HEADCOUNT_ALLOCATION_MISMATCH,
        422,
    )

    after = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(after, {"total_headcount": 100, "version": applicant["version"]})
    assert sorted(
        (entry["code"], entry["headcount"]) for entry in after["jurisdiction_headcounts"]
    ) == [("CA", 40), ("TX", 60)]


def test_the_logical_clock_refuses_to_move_backwards(api):
    """An equal instant is accepted, any earlier instant is ERR_CLOCK_NOT_MONOTONIC.

    PRD: "which must be at or after the current logical clock reading; an
    earlier instant is refused with `ERR_CLOCK_NOT_MONOTONIC` (HTTP 422).
    Setting the clock to the value it already holds is permitted."

    Design: Corner/validations/the_logical_clock_refuses_to_move_backwards
    """
    S.advance_clock(api, "2026-09-15T12:00:00.000Z")

    same = S.advance_clock(api, "2026-09-15T12:00:00.000Z")
    assert_same_instant(same["current_utc"], "2026-09-15T12:00:00.000Z", "current_utc")

    validate_error(
        api.set_clock("2026-09-15T11:59:59.999Z", U.ADMIN), E.ERR_CLOCK_NOT_MONOTONIC, 422
    )
    validate_error(
        api.set_clock("2026-08-01T00:00:00.000Z", U.ADMIN), E.ERR_CLOCK_NOT_MONOTONIC, 422
    )

    forward = S.advance_clock(api, "2026-09-15T12:00:00.001Z")
    assert_same_instant(forward["current_utc"], "2026-09-15T12:00:00.001Z", "current_utc")


def test_policy_periods_for_one_applicant_may_touch_but_not_overlap(api):
    """A genuine overlap is refused while a back-to-back renewal binds.

    PRD: "the new period collides when it begins strictly before an existing
    period ends and that existing period begins strictly before the new one
    ends, so back-to-back terms that merely touch are fine while any genuine
    overlap is `ERR_POLICY_PERIOD_OVERLAP` (HTTP 409)."

    Design: Corner/validations/policy_periods_for_one_applicant_may_touch_but_not_overlap
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Ironwood Freight LLC",
        total_headcount=60,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 60}],
        primary_jurisdiction_code="TX",
    )
    first = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy_one = S.bind_policy(
        api,
        first["id"],
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2027-02-01T00:00:00.000Z",
    )
    second = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )

    validate_error(
        api.create_policy(
            F.policy(
                second["id"],
                effective_from="2027-01-01T00:00:00.000Z",
                effective_to="2027-06-01T00:00:00.000Z",
            ),
            U.UNDERWRITER,
        ),
        E.ERR_POLICY_PERIOD_OVERLAP,
        409,
    )
    unconsumed = get_success_data(api.get_assessment(second["id"], U.UNDERWRITER))
    assert unconsumed["status"] == T.ASSESSMENT_APPROVED

    policy_two = S.bind_policy(
        api,
        second["id"],
        effective_from="2027-02-01T00:00:00.000Z",
        effective_to="2028-02-01T00:00:00.000Z",
    )
    assert_same_instant(policy_two["effective_from"], "2027-02-01T00:00:00.000Z", "effective_from")
    assert_same_instant(policy_two["effective_to"], "2028-02-01T00:00:00.000Z", "effective_to")
    assert policy_two["status"] == T.POLICY_BOUND

    assert get_success_data(api.get_policy(policy_one["id"], U.UNDERWRITER))["status"] == (
        T.POLICY_ACTIVE
    )
    assert get_success_data(api.get_assessment(second["id"], U.UNDERWRITER))["status"] == (
        T.ASSESSMENT_BOUND
    )


def _engagement_world(api):
    """A TX matter engaged 2026-08-06 -> 2026-11-01 with one live [08-06, 09-05] invoice."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-06T00:00:00.000Z",
        period_end="2026-09-05T00:00:00.000Z",
        partner_hours=None,
        associate_hours=10.0,
        paralegal_hours=None,
        block_billed_hours=None,
        expenses_cents=None,
    )
    return {
        "firm_id": firm["id"],
        "policy_id": policy["id"],
        "claim_id": claim["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
    }


def test_invoice_engagement_bounds_outrank_invoice_period_collision(api):
    """Step 16 fires before step 17, so an out-of-window period never reports a collision.

    PRD: "The billing period must lie inside the engagement window —
    `period_start` at or after `engagement_from` and `period_end` strictly
    before `engagement_to` — and a period escaping either edge is
    `ERR_INVOICE_OUTSIDE_ENGAGEMENT` (HTTP 422)."

    Design: Corner/validations/invoice_engagement_bounds_outrank_invoice_period_collision
    """
    world = _engagement_world(api)
    counsel = U.panel_counsel(world["firm_id"])

    validate_error(
        api.submit_invoice(
            world["assignment_id"],
            F.invoice(
                period_start="2026-08-01T00:00:00.000Z",
                period_end="2026-08-20T00:00:00.000Z",
                partner_hours=None,
                associate_hours=4.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            counsel,
        ),
        E.ERR_INVOICE_OUTSIDE_ENGAGEMENT,
        422,
    )
    validate_error(
        api.submit_invoice(
            world["assignment_id"],
            F.invoice(
                period_start="2026-10-20T00:00:00.000Z",
                period_end="2026-11-01T00:00:00.000Z",
                partner_hours=None,
                associate_hours=4.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            counsel,
        ),
        E.ERR_INVOICE_OUTSIDE_ENGAGEMENT,
        422,
    )
    validate_error(
        api.submit_invoice(
            world["assignment_id"],
            F.invoice(
                period_start="2026-09-05T00:00:00.000Z",
                period_end="2026-09-20T00:00:00.000Z",
                partner_hours=None,
                associate_hours=4.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            counsel,
        ),
        E.ERR_INVOICE_PERIOD_OVERLAP,
        409,
    )

    disjoint = S.submit_invoice(
        api,
        world["assignment_id"],
        world["firm_id"],
        period_start="2026-09-06T00:00:00.000Z",
        period_end="2026-09-30T00:00:00.000Z",
        partner_hours=None,
        associate_hours=4.0,
        paralegal_hours=None,
        block_billed_hours=None,
        expenses_cents=None,
    )
    assert disjoint["status"] == T.INVOICE_SUBMITTED

    incumbent = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert incumbent["status"] == T.INVOICE_SUBMITTED
    assert_null(
        incumbent,
        ["billed_fees_cents", "rate_cap_excess_cents", "allowed_amount_cents", "audited_by_user_id"],
    )

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(assignment, {"budget_spent_cents": 0, "status": T.ASSIGNMENT_ACTIVE})


def test_pre_suit_offer_requires_an_administrative_charge_claim(api):
    """Only an ADMIN_CHARGE matter admits an offer; LAWSUIT and DEMAND_LETTER do not.

    PRD: "Only an administrative-charge matter is eligible: a claim whose
    `notice_type` is not `ADMIN_CHARGE` cannot have an offer extended on it and
    cannot have one accepted, and either attempt is `ERR_PRE_SUIT_NOT_ELIGIBLE`
    (HTTP 422)."

    Design: Corner/validations/pre_suit_offer_requires_an_administrative_charge_claim
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    claims = {}
    for key, notice in (
        ("lawsuit", T.NOTICE_LAWSUIT),
        ("demand", T.NOTICE_DEMAND_LETTER),
        ("admin", T.NOTICE_ADMIN_CHARGE),
    ):
        claims[key] = S.accepted_claim(
            api,
            policy["id"],
            claim_type=T.CLAIM_TYPE_DISCRIMINATION,
            claimant_class=T.CLAIMANT_EMPLOYEE,
            notice_type=notice,
            first_notice_at="2026-08-01T00:00:00.000Z",
            alleged_damages_cents=5000000,
        )

    offer = F.pre_suit_offer(
        settlement_offer_cents=2000000, offer_expires_at="2026-09-01T00:00:00.000Z"
    )
    validate_error(
        api.create_pre_suit_resolution(claims["lawsuit"]["id"], offer, U.ADJUSTER),
        E.ERR_PRE_SUIT_NOT_ELIGIBLE,
        422,
    )
    validate_error(
        api.create_pre_suit_resolution(claims["demand"]["id"], offer, U.ADJUSTER),
        E.ERR_PRE_SUIT_NOT_ELIGIBLE,
        422,
    )

    resolution = get_success_data(
        api.create_pre_suit_resolution(claims["admin"]["id"], offer, U.ADJUSTER), 201
    )
    assert_fields(
        resolution,
        {
            "status": T.RESOLUTION_OFFERED,
            "claim_id": claims["admin"]["id"],
            "settlement_offer_cents": 2000000,
        },
    )
    assert_null(resolution, ["incentive_credit_cents"])

    for key in ("lawsuit", "demand"):
        untouched = get_success_data(api.get_claim(claims[key]["id"], U.ADJUSTER))
        assert_fields(
            untouched, {"status": T.CLAIM_COVERAGE_ACCEPTED, "pre_suit_credit_cents": 0}
        )


def test_pre_suit_acceptance_after_the_jurisdiction_window_is_refused(api):
    """136 elapsed days beat the TX window of 120 even though the offer has not expired.

    PRD: "Two temporal conditions then apply, and both failures report
    `ERR_PRE_SUIT_WINDOW_CLOSED` (HTTP 422): the logical clock must be at or
    before `offer_expires_at`, and the elapsed-day count must be inside the
    jurisdiction's window."

    Design: Corner/validations/pre_suit_acceptance_after_the_jurisdiction_window_is_refused
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_ADMIN_CHARGE,
        first_notice_at="2026-08-01T00:00:00.000Z",
        alleged_damages_cents=5000000,
    )
    resolution = get_success_data(
        api.create_pre_suit_resolution(
            claim["id"],
            F.pre_suit_offer(
                settlement_offer_cents=2000000, offer_expires_at="2027-01-01T00:00:00.000Z"
            ),
            U.ADJUSTER,
        ),
        201,
    )
    S.advance_clock(api, "2026-12-15T00:00:00.000Z")

    validate_error(
        api.accept_pre_suit_resolution(resolution["id"], U.ADJUSTER),
        E.ERR_PRE_SUIT_WINDOW_CLOSED,
        422,
    )

    still = get_success_data(api.get_pre_suit_resolution(resolution["id"], U.ADJUSTER))
    assert still["status"] == T.RESOLUTION_OFFERED
    assert_null(still, ["elapsed_days_at_accept", "incentive_credit_cents"])

    unchanged = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        unchanged,
        {
            "pre_suit_credit_cents": 0,
            "applied_retention_cents": 2500000,
            "status": T.CLAIM_COVERAGE_ACCEPTED,
        },
    )
    assert get_success_data(api.get_policy(policy["id"], U.ADJUSTER))["status"] == T.POLICY_ACTIVE


def test_group_attachment_guards_already_grouped_basis_and_locked(api):
    """The three attach refusals, and the lock that an approved retention payment triggers.

    PRD: "An attach is refused when the claim already belongs to a group
    (`ERR_CLAIM_ALREADY_GROUPED`), when the claim's `policy_id` differs from the
    group's (`ERR_OWNERSHIP_MISMATCH`), and when the group is already `LOCKED`
    (`ERR_GROUP_LOCKED`)."

    Design: Corner/validations/group_attachment_guards_already_grouped_basis_and_locked
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    lead = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=9000000,
        claimant_count=12,
    )
    member = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-03T00:00:00.000Z",
        alleged_damages_cents=4000000,
        claimant_count=8,
    )
    latecomer = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-04T00:00:00.000Z",
        alleged_damages_cents=3000000,
        claimant_count=5,
    )
    wage_hour = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_WAGE_AND_HOUR,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-05T00:00:00.000Z",
        alleged_damages_cents=2000000,
        claimant_count=20,
    )
    group = get_success_data(
        api.create_group(
            F.group(policy["id"], lead["id"], T.AGGREGATION_CLASS_ACTION_MEMBER),
            U.CLAIMS_MANAGER,
        ),
        201,
    )

    attached = get_success_data(
        api.attach_claim_to_group(
            group["id"], F.group_attach(member["id"], group["version"]), U.CLAIMS_MANAGER
        )
    )
    assert_fields(
        attached,
        {
            "member_count": 2,
            "shared_retention_cents": 2500000,
            "retention_basis_claim_id": lead["id"],
            "status": T.GROUP_OPEN,
        },
    )
    member_row = get_success_data(api.get_claim(member["id"], U.ADJUSTER))
    assert_fields(
        member_row,
        {"retention_basis": T.RETENTION_GROUP_AGGREGATED, "applied_retention_cents": 0},
    )

    validate_error(
        api.attach_claim_to_group(
            group["id"], F.group_attach(member["id"], attached["version"]), U.CLAIMS_MANAGER
        ),
        E.ERR_CLAIM_ALREADY_GROUPED,
        409,
    )
    validate_error(
        api.attach_claim_to_group(
            group["id"], F.group_attach(wage_hour["id"], attached["version"]), U.CLAIMS_MANAGER
        ),
        E.ERR_GROUP_BASIS_MISMATCH,
        422,
    )
    rejected = get_success_data(api.get_claim(wage_hour["id"], U.ADJUSTER))
    assert_null(rejected, ["related_claim_group_id"])
    assert_fields(
        rejected,
        {"retention_basis": T.RETENTION_PER_CLAIM, "applied_retention_cents": 3750000},
    )

    payment = S.pending_payment(api, policy["id"], lead["id"], 2500000)
    released = get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))
    assert_fields(released, {"retention_portion_cents": 2500000, "insurer_portion_cents": 0})

    locked = get_success_data(api.get_group(group["id"], U.CLAIMS_MANAGER))
    assert_fields(locked, {"retention_paid_cents": 2500000, "status": T.GROUP_LOCKED})

    validate_error(
        api.attach_claim_to_group(
            group["id"], F.group_attach(latecomer["id"], locked["version"]), U.CLAIMS_MANAGER
        ),
        E.ERR_GROUP_LOCKED,
        409,
    )
    assert get_success_data(api.get_group(group["id"], U.CLAIMS_MANAGER))["member_count"] == 2

    final_policy = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        final_policy,
        {"indemnity_paid_cents": 0, "aggregate_limit_remaining_cents": 10000000},
    )


def _sublimit_policy(api, legal_name, third_party_coverage_requested):
    """A TX policy of 25,000,000 with 6,250,000 wage-hour and 10,000,000 third-party carve-outs."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name=legal_name,
        total_headcount=80,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 80}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=25000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=third_party_coverage_requested,
    )
    return S.bind_policy(api, assessment["id"])


def test_wage_hour_sublimit_admits_the_exact_remainder_and_no_more(api):
    """One cent over the wage-hour carve-out is refused; the exact remainder is paid.

    PRD: "when `sublimit_bucket` is `WAGE_HOUR`, an insurer portion exceeding
    the policy's `wage_hour_sublimit_remaining_cents` is
    `ERR_WAGE_HOUR_SUBLIMIT_EXHAUSTED`"

    Design: Corner/validations/wage_hour_sublimit_admits_the_exact_remainder_and_no_more
    """
    policy = _sublimit_policy(api, "Northgate Warehousing LLC", None)
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_WAGE_AND_HOUR,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=20000000,
        claimant_count=60,
    )

    over = S.pending_payment(api, policy["id"], claim["id"], 10000001)
    assert_fields(
        over,
        {
            "retention_portion_cents": 3750000,
            "insurer_portion_cents": 6250001,
            "sublimit_bucket": T.BUCKET_WAGE_HOUR,
        },
    )
    validate_error(
        api.approve_payment(over["id"], U.CLAIMS_MANAGER),
        E.ERR_WAGE_HOUR_SUBLIMIT_EXHAUSTED,
        409,
    )
    assert get_success_data(api.get_payment(over["id"], U.ADJUSTER))["status"] == (
        T.PAYMENT_PENDING_APPROVAL
    )
    held = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert held["wage_hour_sublimit_remaining_cents"] == 6250000
    assert get_success_data(api.get_claim(claim["id"], U.ADJUSTER))["retention_satisfied_cents"] == 0

    exact = S.pending_payment(api, policy["id"], claim["id"], 10000000)
    assert_fields(
        exact, {"retention_portion_cents": 3750000, "insurer_portion_cents": 6250000}
    )
    released = get_success_data(api.approve_payment(exact["id"], U.CLAIMS_MANAGER))
    assert released["status"] == T.PAYMENT_APPROVED

    eroded = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        eroded,
        {
            "wage_hour_sublimit_remaining_cents": 0,
            "indemnity_paid_cents": 6250000,
            "aggregate_limit_remaining_cents": 18750000,
            "limit_posture": T.POSTURE_ERODED,
            "third_party_sublimit_remaining_cents": 10000000,
        },
    )
    resolved = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        resolved,
        {
            "retention_satisfied_cents": 3750000,
            "indemnity_paid_cents": 6250000,
            "status": T.CLAIM_RESOLVED,
        },
    )

    penny = S.pending_payment(api, policy["id"], claim["id"], 1)
    assert_fields(penny, {"retention_portion_cents": 0, "insurer_portion_cents": 1})
    validate_error(
        api.approve_payment(penny["id"], U.CLAIMS_MANAGER),
        E.ERR_WAGE_HOUR_SUBLIMIT_EXHAUSTED,
        409,
    )


def test_third_party_sublimit_admits_the_exact_remainder_and_no_more(api):
    """A customer claimant draws the third-party carve-out and leaves wage-hour alone.

    PRD: "when it is `THIRD_PARTY`, an insurer portion exceeding
    `third_party_sublimit_remaining_cents` is
    `ERR_THIRD_PARTY_SUBLIMIT_EXHAUSTED`"

    Design: Corner/validations/third_party_sublimit_admits_the_exact_remainder_and_no_more
    """
    policy = _sublimit_policy(api, "Summit Row Retail LLC", True)
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_CUSTOMER,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=20000000,
    )
    assert_fields(
        claim,
        {"coverage_bucket": T.BUCKET_THIRD_PARTY, "per_claim_retention_cents": 3125000},
    )

    over = S.pending_payment(
        api, policy["id"], claim["id"], 13125001, payment_basis=T.PAYMENT_BASIS_JUDGMENT
    )
    assert_fields(
        over,
        {
            "retention_portion_cents": 3125000,
            "insurer_portion_cents": 10000001,
            "sublimit_bucket": T.BUCKET_THIRD_PARTY,
        },
    )
    validate_error(
        api.approve_payment(over["id"], U.CLAIMS_MANAGER),
        E.ERR_THIRD_PARTY_SUBLIMIT_EXHAUSTED,
        409,
    )
    assert get_success_data(api.get_payment(over["id"], U.ADJUSTER))["status"] == (
        T.PAYMENT_PENDING_APPROVAL
    )

    exact = S.pending_payment(
        api, policy["id"], claim["id"], 13125000, payment_basis=T.PAYMENT_BASIS_JUDGMENT
    )
    assert exact["insurer_portion_cents"] == 10000000
    released = get_success_data(api.approve_payment(exact["id"], U.CLAIMS_MANAGER))
    assert released["status"] == T.PAYMENT_APPROVED

    eroded = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        eroded,
        {
            "third_party_sublimit_cents": 10000000,
            "third_party_sublimit_remaining_cents": 0,
            "wage_hour_sublimit_remaining_cents": 6250000,
            "indemnity_paid_cents": 10000000,
            "aggregate_limit_remaining_cents": 15000000,
            "limit_posture": T.POSTURE_ERODED,
        },
    )
    resolved = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        resolved, {"retention_satisfied_cents": 3125000, "status": T.CLAIM_RESOLVED}
    )


def test_defense_invoice_approval_waits_for_the_retention_and_a_live_assignment(api):
    """Step 25 blocks the audited invoice until the retention attaches; step 9 bars the closed matter.

    PRD: "the claim's retention must have attached, meaning its
    `retention_satisfied_cents` is at or above its `applied_retention_cents`, or
    else the claim belongs to a related-claim group whose status is `LOCKED`
    (`ERR_RETENTION_NOT_SATISFIED`)"

    Design: Corner/validations/defense_invoice_approval_waits_for_the_retention_and_a_live_assignment
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_HARASSMENT,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-06T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=3000000,
        panel_firm_id=firm["id"],
    )
    invoice = S.audited_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-06T00:00:00.000Z",
        period_end="2026-09-05T00:00:00.000Z",
        partner_hours=None,
        associate_hours=10.0,
        paralegal_hours=None,
        block_billed_hours=None,
        expenses_cents=None,
    )
    assert_fields(
        invoice,
        {
            "billed_fees_cents": 510000,
            "rate_cap_excess_cents": 60000,
            "allowed_amount_cents": 450000,
            "status": T.INVOICE_UNDER_AUDIT,
            "audited_by_user_id": U.ADJ_001,
        },
    )

    validate_error(
        api.approve_invoice(invoice["id"], U.ADJUSTER_2), E.ERR_RETENTION_NOT_SATISFIED, 409
    )
    assert get_success_data(api.get_invoice(invoice["id"], U.ADJUSTER))["status"] == (
        T.INVOICE_UNDER_AUDIT
    )
    held_claim = get_success_data(api.get_claim(claim["id"], U.ADJUSTER))
    assert_fields(
        held_claim, {"retention_satisfied_cents": 0, "applied_retention_cents": 2500000}
    )
    assert get_success_data(api.get_assignment(assignment["id"], U.ADJUSTER))[
        "budget_spent_cents"
    ] == 0

    payment = S.pending_payment(api, policy["id"], claim["id"], 2500000)
    assert_fields(payment, {"retention_portion_cents": 2500000, "insurer_portion_cents": 0})
    get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))
    assert get_success_data(api.get_claim(claim["id"], U.ADJUSTER))[
        "retention_satisfied_cents"
    ] == 2500000

    approved = get_success_data(api.approve_invoice(invoice["id"], U.ADJUSTER_2))
    assert_fields(
        approved,
        {
            "status": T.INVOICE_APPROVED,
            "allowed_amount_cents": 450000,
        },
    )
    funded = get_success_data(api.get_assignment(assignment["id"], U.ADJUSTER))
    assert_fields(funded, {"budget_spent_cents": 450000, "budget_remaining_cents": 2550000})
    spent = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert_fields(
        spent, {"defense_spend_cents": 450000, "aggregate_limit_remaining_cents": 9550000}
    )

    closed = get_success_data(api.close_assignment(assignment["id"], U.ADJUSTER))
    assert closed["status"] == T.ASSIGNMENT_CLOSED
    assert get_success_data(api.get_panel_firm(firm["id"], U.ADMIN))["open_matter_count"] == 0

    validate_error(
        api.submit_invoice(
            assignment["id"],
            F.invoice(
                period_start="2026-09-06T00:00:00.000Z",
                period_end="2026-09-30T00:00:00.000Z",
                partner_hours=None,
                associate_hours=4.0,
                paralegal_hours=None,
                block_billed_hours=None,
                expenses_cents=None,
            ),
            U.panel_counsel(firm["id"]),
        ),
        E.ERR_ASSIGNMENT_CLOSED,
        409,
    )
    rows, meta = validate_paginated(
        api.list_invoices(U.ADJUSTER, {"defense_assignment_id": assignment["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [invoice["id"]]


def test_first_notice_on_the_inclusive_lower_bound_is_covered(api):
    """Notice exactly at inception is covered; one millisecond earlier and expiry itself are not.

    PRD: "`first_notice_at` must be at or after the policy's `effective_from`
    and strictly before its `effective_to`; notice before inception or at or
    after expiry is `ERR_CLAIM_OUTSIDE_POLICY_PERIOD` (HTTP 422)."

    Design: Corner/validations/first_notice_on_the_inclusive_lower_bound_is_covered
    """
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Bayline Foods LLC",
        total_headcount=40,
        prior_year_separations=4,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 40}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_approved_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=10000000,
        requested_retention_cents=2500000,
        third_party_coverage_requested=None,
    )
    policy = S.bind_policy(api, assessment["id"])

    boundary = S.report_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_WRONGFUL_TERMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-01T00:00:00.000Z",
        alleged_damages_cents=3000000,
    )
    assert_same_instant(
        boundary["first_notice_at"], "2026-08-01T00:00:00.000Z", "first_notice_at"
    )
    assert_fields(
        boundary,
        {
            "status": T.CLAIM_REPORTED,
            "coverage_bucket": T.BUCKET_FIRST_PARTY,
            "retention_basis": T.RETENTION_PER_CLAIM,
            "claimant_count": 1,
            "reopen_count": 0,
            "retention_satisfied_cents": 0,
            "indemnity_paid_cents": 0,
        },
    )

    for instant in ("2026-07-31T23:59:59.999Z", "2027-08-01T00:00:00.000Z"):
        validate_error(
            api.report_claim(
                policy["id"],
                F.claim(
                    claim_type=T.CLAIM_TYPE_WRONGFUL_TERMINATION,
                    claimant_class=T.CLAIMANT_EMPLOYEE,
                    notice_type=T.NOTICE_LAWSUIT,
                    first_notice_at=instant,
                    alleged_damages_cents=3000000,
                ),
                U.ADJUSTER,
            ),
            E.ERR_CLAIM_OUTSIDE_POLICY_PERIOD,
            422,
        )

    assert get_success_data(api.get_policy(policy["id"], U.ADJUSTER))["status"] == T.POLICY_ACTIVE
    _, meta = validate_paginated(api.list_claims(U.ADJUSTER, {"policy_id": policy["id"]}))
    assert meta["total_count"] == 1
