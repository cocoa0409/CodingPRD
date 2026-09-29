"""Combinatorial formulas: pinned per-jurisdiction rounding and the invoice audit order."""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields, assert_money


def _priced_two_jurisdiction_assessment(api):
    S.create_jurisdiction(api, "CA")
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(api)
    assessment = S.create_priced_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=200000000,
        requested_retention_cents=5000000,
        third_party_coverage_requested=True,
    )
    return applicant["id"], assessment


def test_base_premium_rounds_each_jurisdiction_share_before_summing(api):
    """Two half-cent shares round up individually rather than once on the total.

    PRD: "The order is pinned: each jurisdiction's share is rounded first and
    the rounded shares are then added. Rounding the single product of
    `total_headcount` and the per-employee amount instead can differ from the
    correct answer by as much as one cent for every jurisdiction beyond the
    first."

    Design: Difficulty/combinatorial_formula/premium_per_jurisdiction_round_then_sum_order
    """
    applicant_id, assessment = _priced_two_jurisdiction_assessment(api)

    assert_money(assessment["base_premium_cents"], 14278501, "base_premium_cents")
    assert assessment["base_premium_cents"] != 14278500
    applicant = get_success_data(api.get_applicant(applicant_id, U.UNDERWRITER))
    assert_fields(applicant, {"turnover_pct": 24.00, "hazard_load_pct": 0.215, "exposure_score": 75.20})


def test_every_premium_component_is_rounded_at_its_own_step(api):
    """The six components and the indicated premium all land on their pinned cents.

    PRD: "The **premium calculation** proceeds in eight pinned steps and
    produces six components plus a result. Every component is rounded half up
    to whole cents at the step that produces it."

    Design: Difficulty/combinatorial_formula/premium_per_jurisdiction_round_then_sum_order
    """
    _applicant_id, assessment = _priced_two_jurisdiction_assessment(api)

    assert_fields(
        assessment,
        {
            "base_premium_cents": 14278501,
            "turnover_load_cents": 1998990,
            "hazard_load_cents": 3069878,
            "limit_load_cents": 1427850,
            "retention_credit_cents": 713925,
            "risk_mgmt_credit_cents": 0,
            "indicated_premium_cents": 20061294,
            "exposure_score_snapshot": 75.20,
            "status": T.ASSESSMENT_REFERRED,
            "credit_basis_stale": False,
        },
    )
    assert assessment["indicated_premium_cents"] != 20061293


def _audited_invoice_world(api):
    """A client-directed engagement with one invoice carrying block time and expenses."""
    world = S.underwritten_policy(api)
    firm = S.create_panel_firm(
        api,
        name="Ashford & Vance LLP",
        tier=T.TIER_NATIONAL,
        jurisdiction_codes=["CA", "TX"],
        partner_rate_cents_per_hour=92000,
        associate_rate_cents_per_hour=51000,
        paralegal_rate_cents_per_hour=18000,
        capacity_open_matters=3,
    )
    claim = S.accepted_claim(
        api,
        world["policy_id"],
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=25000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=5000000,
        litigation_guideline_version=1,
        panel_firm_id=firm["id"],
    )
    invoice = S.submit_invoice(
        api,
        assignment["id"],
        firm["id"],
        period_start="2026-08-01T00:00:00.000Z",
        period_end="2026-08-31T00:00:00.000Z",
        partner_hours=12.5,
        associate_hours=40.0,
        paralegal_hours=8.0,
        block_billed_hours=15.0,
        expenses_cents=420000,
    )
    return {"firm": firm, "assignment": assignment, "invoice": invoice}


def test_expense_allowance_keys_off_the_fees_left_after_both_reductions(api):
    """0.08 of the post-block allowed fees, not of billed or post-rate-cap fees.

    PRD: "The base of this cap is pinned: it is the allowed fees **after both**
    the rate-cap and block-billing reductions, not the originally billed fees
    and not the post-rate-cap fees."

    Design: Difficulty/combinatorial_formula/invoice_audit_expense_cap_evaluation_order
    """
    world = _audited_invoice_world(api)
    audited = get_success_data(api.audit_invoice(world["invoice"]["id"], U.ADJUSTER))

    assert_money(audited["expense_disallowance_cents"], 200911, "expense_disallowance_cents")
    assert audited["expense_disallowance_cents"] != 153280
    assert audited["expense_disallowance_cents"] != 189480
    assert_fields(
        audited,
        {
            "allowed_amount_cents": 2957705,
            "guideline_reduction_cents": 796295,
            "disallowed_amount_cents": 796295,
        },
    )


def test_audit_computes_the_reductions_without_committing_the_budget(api):
    """The audit writes the seven outputs and leaves budget_spent_cents at zero.

    PRD: "Auditing is callable from `SUBMITTED` and from `ADJUSTED`; from any
    other status it is `ERR_INVOICE_NOT_AUDITABLE`. Either leg lands the invoice
    in `UNDER_AUDIT`, writes all seven audit output fields, and sets
    `audited_by_user_id` to the acting `X-User-ID`."

    Design: Difficulty/combinatorial_formula/invoice_audit_expense_cap_evaluation_order
    """
    world = _audited_invoice_world(api)
    audited = get_success_data(api.audit_invoice(world["invoice"]["id"], U.ADJUSTER))

    assert_fields(
        audited,
        {
            "billed_fees_cents": 3334000,
            "rate_cap_excess_cents": 452500,
            "block_reduction_cents": 142884,
            "status": T.INVOICE_UNDER_AUDIT,
            "audited_by_user_id": U.ADJ_001,
        },
    )
    assignment = get_success_data(api.get_assignment(world["assignment"]["id"], U.ADJUSTER))
    assert_fields(
        assignment,
        {
            "partner_rate_cents_per_hour": 92000,
            "associate_rate_cents_per_hour": 51000,
            "paralegal_rate_cents_per_hour": 18000,
            "selection_reason": T.SELECTION_CLIENT_DIRECTED,
            "budget_spent_cents": 0,
        },
    )
    firm = get_success_data(api.get_panel_firm(world["firm"]["id"], U.ADJUSTER))
    assert_money(firm["blended_rate_cents"], 60400, "blended_rate_cents")
