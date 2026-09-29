"""Validation-precedence pairs: the higher-priority check reports, the lower one loses."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import assert_fields


def _invoice_on_a_tight_budget(api, budget_cap_cents):
    """An accepted retaliation claim with one audited invoice on a matter of the given cap."""
    S.create_jurisdictions(api, ["CA", "TX"])
    plan_id = S.create_active_rate_plan(api)["id"]
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
    applicant = S.create_applicant(api)
    assessment = S.create_approved_assessment(api, applicant["id"], plan_id)
    policy = S.bind_policy(api, assessment["id"])
    claim = S.accepted_claim(
        api,
        policy["id"],
        claim_type=T.CLAIM_TYPE_RETALIATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        alleged_damages_cents=22000000,
    )
    assignment = S.create_assignment(
        api,
        claim["id"],
        engagement_from="2026-08-01T00:00:00.000Z",
        engagement_to="2026-11-01T00:00:00.000Z",
        budget_cap_cents=budget_cap_cents,
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
    get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))
    return {
        "firm_id": firm["id"],
        "policy_id": policy["id"],
        "claim_id": claim["id"],
        "assignment_id": assignment["id"],
        "invoice_id": invoice["id"],
    }


def _disputed_invoice_over_budget(api):
    world = _invoice_on_a_tight_budget(api, 1000000)
    get_success_data(
        api.dispute_invoice(
            world["invoice_id"],
            F.invoice_dispute(
                "Block-billed entries re-itemised and travel expenses withdrawn",
                block_billed_hours=0.0,
                expenses_cents=200000,
            ),
            U.panel_counsel(world["firm_id"]),
        )
    )
    return world


def test_invoice_own_state_outranks_the_matter_budget(api):
    """An ADJUSTED invoice over budget reports the state code, not the fiscal one.

    PRD: "Approving a defense invoice that a dispute returned to `ADJUSTED`
    while its recomputed allowed amount would also blow the matter budget
    reports `ERR_INVOICE_NOT_APPROVABLE`, because the own-state check outranks
    the fiscal check."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_precedence_over_budget_cap
    """
    world = _disputed_invoice_over_budget(api)
    body = validate_error(
        api.approve_invoice(world["invoice_id"], U.ADJUSTER_2), E.ERR_INVOICE_NOT_APPROVABLE, 409
    )
    error_id = body["error_id"]
    assert error_id not in (E.ERR_BUDGET_CAP_EXCEEDED, E.ERR_RETENTION_NOT_SATISFIED)

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert invoice["status"] == T.INVOICE_ADJUSTED


def test_the_budget_and_retention_checks_were_both_genuinely_violated(api):
    """The two lower-priority checks would each have failed, and neither reported.

    PRD: "The matter's defense budget must accommodate the invoice → otherwise
    `ERR_BUDGET_CAP_EXCEEDED` (409), on invoice approval."

    Design: Difficulty/priority_pair_validation_conflict/invoice_state_precedence_over_budget_cap
    """
    world = _disputed_invoice_over_budget(api)
    validate_error(
        api.approve_invoice(world["invoice_id"], U.ADJUSTER_2), E.ERR_INVOICE_NOT_APPROVABLE, 409
    )

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert invoice["allowed_amount_cents"] == 3081500

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(
        assignment,
        {
            "budget_cap_cents": 1000000,
            "budget_spent_cents": 0,
            "budget_remaining_cents": 1000000,
        },
    )

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(claim, {"applied_retention_cents": 5000000, "retention_satisfied_cents": 0})

    policy = get_success_data(api.get_policy(world["policy_id"], U.ADJUSTER))
    assert policy["defense_spend_cents"] == 0


def test_the_four_eyes_gate_outranks_the_retention_gate(api):
    """The auditor approving their own invoice reports the segregation code.

    PRD: "When the very user who audited an invoice tries to approve it on a
    claim whose retention is not yet satisfied, the answer is
    `ERR_SEGREGATION_OF_DUTIES`, because the four-eyes gate outranks the
    retention gate."

    Design: Difficulty/priority_pair_validation_conflict/sod_precedence_over_retention_not_satisfied
    """
    world = _invoice_on_a_tight_budget(api, 5000000)
    body = validate_error(
        api.approve_invoice(world["invoice_id"], U.ADJUSTER), E.ERR_SEGREGATION_OF_DUTIES, 403
    )
    error_id = body["error_id"]
    assert error_id != E.ERR_RETENTION_NOT_SATISFIED

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert_fields(
        invoice, {"status": T.INVOICE_UNDER_AUDIT, "audited_by_user_id": U.ADJ_001}
    )


def test_the_retention_gate_was_genuinely_violated_and_still_lost(api):
    """The retention was unsatisfied while the budget check would have passed.

    PRD: "Insurer money may not leave before the retention attaches, so an
    invoice may only be approved once the claim's retention is satisfied or its
    group is locked → otherwise `ERR_RETENTION_NOT_SATISFIED` (409), on invoice
    approval."

    Design: Difficulty/priority_pair_validation_conflict/sod_precedence_over_retention_not_satisfied
    """
    world = _invoice_on_a_tight_budget(api, 5000000)
    validate_error(
        api.approve_invoice(world["invoice_id"], U.ADJUSTER), E.ERR_SEGREGATION_OF_DUTIES, 403
    )

    claim = get_success_data(api.get_claim(world["claim_id"], U.ADJUSTER))
    assert_fields(claim, {"retention_satisfied_cents": 0, "applied_retention_cents": 5000000})

    invoice = get_success_data(api.get_invoice(world["invoice_id"], U.ADJUSTER))
    assert invoice["allowed_amount_cents"] == 2957705

    assignment = get_success_data(api.get_assignment(world["assignment_id"], U.ADJUSTER))
    assert_fields(assignment, {"budget_cap_cents": 5000000, "budget_spent_cents": 0})


def _first_party_only_policy(api):
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
    return S.bind_policy(api, assessment["id"])


def test_the_third_party_election_check_outranks_the_policy_period_check(api):
    """A customer claim outside the term reports the election code.

    PRD: "Reporting a customer-claimant claim on a policy that never elected
    third-party coverage, with a `first_notice_at` also outside the policy
    period, reports `ERR_THIRD_PARTY_COVERAGE_NOT_ELECTED`, because the
    coverage-election check outranks the temporal check."

    Design: Difficulty/priority_pair_validation_conflict/third_party_election_precedence_over_policy_period
    """
    policy = _first_party_only_policy(api)
    assert policy["third_party_coverage_elected"] is False

    body = validate_error(
        api.report_claim(
            policy["id"],
            F.claim(
                claim_type=T.CLAIM_TYPE_DISCRIMINATION,
                claimant_class=T.CLAIMANT_CUSTOMER,
                notice_type=T.NOTICE_LAWSUIT,
                first_notice_at="2025-01-15T00:00:00.000Z",
                alleged_damages_cents=1000000,
            ),
            U.ADJUSTER,
        ),
        E.ERR_THIRD_PARTY_COVERAGE_NOT_ELECTED,
        422,
    )
    error_id = body["error_id"]
    assert error_id != E.ERR_CLAIM_OUTSIDE_POLICY_PERIOD


def test_the_refused_intake_leaves_no_claim_row_behind(api):
    """The temporal rule was violated too, and nothing was persisted either way.

    PRD: "`first_notice_at` must be at or after the policy's `effective_from`
    and strictly before its `effective_to`; notice before inception or at or
    after expiry is `ERR_CLAIM_OUTSIDE_POLICY_PERIOD` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/third_party_election_precedence_over_policy_period
    """
    policy = _first_party_only_policy(api)
    assert policy["effective_from"].startswith("2026-08-01")

    validate_error(
        api.report_claim(
            policy["id"],
            F.claim(
                claim_type=T.CLAIM_TYPE_DISCRIMINATION,
                claimant_class=T.CLAIMANT_CUSTOMER,
                notice_type=T.NOTICE_LAWSUIT,
                first_notice_at="2025-01-15T00:00:00.000Z",
                alleged_damages_cents=1000000,
            ),
            U.ADJUSTER,
        ),
        E.ERR_THIRD_PARTY_COVERAGE_NOT_ELECTED,
        422,
    )

    rows, meta = validate_paginated(api.list_claims(U.ADJUSTER, {"policy_id": policy["id"]}))
    assert meta["total_count"] == 0
    assert rows == []

    fresh = get_success_data(api.get_policy(policy["id"], U.ADJUSTER))
    assert fresh["aggregate_limit_remaining_cents"] == 10000000
