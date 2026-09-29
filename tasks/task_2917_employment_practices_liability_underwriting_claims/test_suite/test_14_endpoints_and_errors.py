"""Endpoint-shape reads, terminal-state refusals and the reachable error catalogue."""

from prd_bench_local_runner.testing import get_success_data, validate_error, validate_paginated

from test_helpers import api_errors as E
from test_helpers import factories as F
from test_helpers import fixtures as S
from test_helpers import test_users as U
from test_helpers import types as T
from test_helpers.assertions import (
    assert_error_meta_only,
    assert_fields,
    assert_version_bumped_by,
)


LEDGER_FIELDS = [
    "aggregate_limit_cents",
    "indemnity_paid_cents",
    "defense_spend_cents",
    "aggregate_limit_remaining_cents",
    "wage_hour_sublimit_cents",
    "wage_hour_sublimit_remaining_cents",
    "third_party_sublimit_cents",
    "third_party_sublimit_remaining_cents",
    "limit_posture",
]


def test_the_limit_ledger_read_reconciles_field_for_field_with_the_policy_row(api):
    """A partly eroded 10,000,000-cent policy: the computed ledger mirrors the stored row.

    PRD: "One read is purely computed rather than a stored row: the policy limit
    ledger reconciles a policy's aggregate limit against its indemnity and
    defense spend in a single object reporting `policy_id`,
    `aggregate_limit_cents`, `indemnity_paid_cents`, `defense_spend_cents`,
    `aggregate_limit_remaining_cents`, `wage_hour_sublimit_cents`,
    `wage_hour_sublimit_remaining_cents`, `third_party_sublimit_cents`,
    `third_party_sublimit_remaining_cents` and `limit_posture`."

    Design: Corner/endpoints/limit_ledger_read_reconciles_with_the_policy_row
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
    policy_id = S.bind_policy(api, assessment["id"])["id"]
    claim = S.accepted_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_RETALIATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_LAWSUIT,
        first_notice_at="2026-08-02T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    payment = S.pending_payment(api, policy_id, claim["id"], 4000000)
    get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))

    response = api.get_limit_ledger(policy_id, U.UW_MANAGER)
    ledger = get_success_data(response)
    assert response.json()["response_type"] == "object"
    assert_fields(
        ledger,
        {
            "policy_id": policy_id,
            "aggregate_limit_cents": 10000000,
            "indemnity_paid_cents": 1500000,
            "defense_spend_cents": 0,
            "aggregate_limit_remaining_cents": 8500000,
            "wage_hour_sublimit_cents": 2500000,
            "wage_hour_sublimit_remaining_cents": 2500000,
            "third_party_sublimit_cents": 4000000,
            "third_party_sublimit_remaining_cents": 4000000,
            "limit_posture": T.POSTURE_ERODED,
        },
    )

    policy = get_success_data(api.get_policy(policy_id, U.UW_MANAGER))
    assert ledger["policy_id"] == policy["id"]
    for field in LEDGER_FIELDS:
        assert ledger[field] == policy[field], (
            f"ledger.{field} ({ledger[field]!r}) must equal policy.{field} ({policy[field]!r})"
        )


def _larkspur_priced_assessment(api):
    """A PRICED 100,000,000-cent quote for a 100-employee TX clinic group."""
    S.create_jurisdiction(api, "TX")
    plan_id = S.create_active_rate_plan(api)["id"]
    applicant = S.create_applicant(
        api,
        legal_name="Larkspur Clinics LLC",
        total_headcount=100,
        prior_year_separations=0,
        jurisdiction_headcounts=[{"code": "TX", "headcount": 100}],
        primary_jurisdiction_code="TX",
    )
    assessment = S.create_priced_assessment(
        api,
        applicant["id"],
        plan_id,
        requested_aggregate_limit_cents=100000000,
        requested_retention_cents=0,
        third_party_coverage_requested=None,
    )
    return applicant, assessment


def test_a_rejected_assessment_is_terminal_for_approve_reject_and_reprice(api):
    """REJECTED refuses every later decision while keeping the pricing it was rejected on.

    PRD: "Rejecting an assessment, likewise from `PRICED` or `REFERRED`, records
    a mandatory `rejection_reason` and moves it to `REJECTED`, which is terminal
    — as are `SUPERSEDED` and `BOUND`."

    Design: Corner/endpoints/rejecting_an_assessment_is_terminal_for_every_later_decision
    """
    _applicant, assessment = _larkspur_priced_assessment(api)
    assert_fields(
        assessment,
        {
            "status": T.ASSESSMENT_PRICED,
            "indicated_premium_cents": 4132206,
            "priced_by_user_id": U.UW_001,
        },
    )

    rejected = get_success_data(
        api.reject_assessment(assessment["id"], "Loss history outside appetite", U.UW_MANAGER)
    )
    assert_fields(
        rejected,
        {
            "status": T.ASSESSMENT_REJECTED,
            "rejection_reason": "Loss history outside appetite",
            "indicated_premium_cents": 4132206,
            "priced_by_user_id": U.UW_001,
        },
    )

    validate_error(
        api.approve_assessment(assessment["id"], U.UW_MANAGER),
        E.ERR_ASSESSMENT_NOT_DECIDABLE,
        409,
    )
    validate_error(
        api.reject_assessment(assessment["id"], "Second thoughts", U.UW_MANAGER),
        E.ERR_ASSESSMENT_NOT_DECIDABLE,
        409,
    )
    validate_error(
        api.price_assessment(assessment["id"], U.UNDERWRITER),
        E.ERR_ASSESSMENT_NOT_PRICEABLE,
        409,
    )

    final = get_success_data(api.get_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(
        final,
        {
            "status": T.ASSESSMENT_REJECTED,
            "rejection_reason": "Loss history outside appetite",
            "indicated_premium_cents": 4132206,
        },
    )
    assert_version_bumped_by(assessment, final, 1)


def test_patching_exposure_data_restates_the_score_and_stales_the_quote(api):
    """separations_since_assessment alone is harmless; prior_year_separations refers the quote.

    PRD: "a revision that supplies `total_headcount`, `prior_year_separations`,
    `jurisdiction_headcounts` or `primary_jurisdiction_code` fires the same
    `PRICED → REFERRED` staling described above, whereas a revision that
    supplies **only** `separations_since_assessment` does not"

    Design: Corner/endpoints/patching_applicant_exposure_data_restates_the_score_and_stales_the_quote
    """
    applicant, assessment = _larkspur_priced_assessment(api)
    before = get_success_data(api.get_applicant(applicant["id"], U.UNDERWRITER))
    assert_fields(before, {"turnover_pct": 0.00, "exposure_score": 28.00})

    harmless = get_success_data(
        api.patch_applicant(applicant["id"], {"separations_since_assessment": 3}, U.UNDERWRITER)
    )
    assert_fields(
        harmless,
        {"separations_since_assessment": 3, "turnover_pct": 0.00, "exposure_score": 28.00},
    )
    assert_version_bumped_by(before, harmless, 1)
    unstaled = get_success_data(api.get_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(unstaled, {"status": T.ASSESSMENT_PRICED, "credit_basis_stale": False})

    staling = get_success_data(
        api.patch_applicant(applicant["id"], {"prior_year_separations": 25}, U.UNDERWRITER)
    )
    assert_fields(
        staling,
        {"prior_year_separations": 25, "turnover_pct": 25.00, "exposure_score": 48.00},
    )
    assert_version_bumped_by(harmless, staling, 1)

    staled = get_success_data(api.get_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(
        staled,
        {
            "status": T.ASSESSMENT_REFERRED,
            "credit_basis_stale": True,
            "indicated_premium_cents": 4132206,
        },
    )

    validate_error(
        api.approve_assessment(assessment["id"], U.UW_MANAGER),
        E.ERR_CREDIT_BASIS_STALE,
        409,
    )

    repriced = get_success_data(api.price_assessment(assessment["id"], U.UNDERWRITER))
    assert_fields(
        repriced,
        {
            "status": T.ASSESSMENT_PRICED,
            "credit_basis_stale": False,
            "turnover_load_cents": 540663,
            "indicated_premium_cents": 4672869,
        },
    )

    approved = get_success_data(api.approve_assessment(assessment["id"], U.UW_MANAGER))
    assert_fields(
        approved,
        {"status": T.ASSESSMENT_APPROVED, "indicated_premium_cents": 4672869},
    )


def test_every_scoped_not_found_error_is_reachable_from_its_own_read(api):
    """Thirteen unminted ids, thirteen distinct 404 codes, plus the computed ledger read.

    PRD: "Every identifier in the URL path resolves to an existing row of the
    expected type → otherwise the 404 matching that path segment:
    `ERR_JURISDICTION_NOT_FOUND`, `ERR_RATE_PLAN_NOT_FOUND`,
    `ERR_APPLICANT_NOT_FOUND`, `ERR_SERVICE_NOT_FOUND`,
    `ERR_ASSESSMENT_NOT_FOUND`, `ERR_POLICY_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`,
    `ERR_GROUP_NOT_FOUND`, `ERR_PANEL_FIRM_NOT_FOUND`,
    `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_INVOICE_NOT_FOUND`,
    `ERR_PAYMENT_NOT_FOUND` or `ERR_RESOLUTION_NOT_FOUND`."

    Design: Corner/errors/every_scoped_not_found_error_is_reachable_from_its_own_read
    """
    probes = [
        ("jurisdiction", api.get_jurisdiction, "00000000-0000-4000-8000-000000000001", E.ERR_JURISDICTION_NOT_FOUND),
        ("rate plan", api.get_rate_plan, "00000000-0000-4000-8000-000000000002", E.ERR_RATE_PLAN_NOT_FOUND),
        ("applicant", api.get_applicant, "00000000-0000-4000-8000-000000000003", E.ERR_APPLICANT_NOT_FOUND),
        ("risk service", api.get_risk_service, "00000000-0000-4000-8000-000000000004", E.ERR_SERVICE_NOT_FOUND),
        ("assessment", api.get_assessment, "00000000-0000-4000-8000-000000000005", E.ERR_ASSESSMENT_NOT_FOUND),
        ("policy", api.get_policy, "00000000-0000-4000-8000-000000000006", E.ERR_POLICY_NOT_FOUND),
        ("claim", api.get_claim, "00000000-0000-4000-8000-000000000007", E.ERR_CLAIM_NOT_FOUND),
        ("group", api.get_group, "00000000-0000-4000-8000-000000000008", E.ERR_GROUP_NOT_FOUND),
        ("panel firm", api.get_panel_firm, "00000000-0000-4000-8000-000000000009", E.ERR_PANEL_FIRM_NOT_FOUND),
        ("assignment", api.get_assignment, "00000000-0000-4000-8000-00000000000a", E.ERR_ASSIGNMENT_NOT_FOUND),
        ("invoice", api.get_invoice, "00000000-0000-4000-8000-00000000000b", E.ERR_INVOICE_NOT_FOUND),
        ("payment", api.get_payment, "00000000-0000-4000-8000-00000000000c", E.ERR_PAYMENT_NOT_FOUND),
        ("resolution", api.get_pre_suit_resolution, "00000000-0000-4000-8000-00000000000d", E.ERR_RESOLUTION_NOT_FOUND),
        ("limit ledger", api.get_limit_ledger, "00000000-0000-4000-8000-00000000000e", E.ERR_POLICY_NOT_FOUND),
    ]
    for label, read, unminted_id, expected in probes:
        response = read(unminted_id, U.ADMIN)
        data = validate_error(response, expected, 404)
        assert data["message"], f"{label} 404 must carry a non-empty message"
        assert_error_meta_only(response.json())


def test_claim_lifecycle_and_reference_data_state_errors_are_all_reachable(api):
    """Eight own-state refusals walked out along one claim, one firm and one service.

    PRD: "The target entity's own current status permits the requested transition
    → otherwise the state error naming that operation"

    PRD: "Closing the file is an adjuster action available from `COVERAGE_DENIED`
    and from `RESOLVED`; from any other status it is `ERR_CLAIM_NOT_CLOSABLE`."

    Design: Corner/errors/claim_lifecycle_and_reference_data_state_errors_are_all_reachable
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
    policy_id = S.bind_policy(api, assessment["id"])["id"]
    service = S.create_risk_service(
        api,
        applicant["id"],
        service_type=T.SERVICE_HOTLINE,
        credit_pct=0.06,
        effective_from="2026-08-01T00:00:00.000Z",
        effective_to="2027-08-01T00:00:00.000Z",
    )
    claim = S.report_claim(
        api,
        policy_id,
        claim_type=T.CLAIM_TYPE_DISCRIMINATION,
        claimant_class=T.CLAIMANT_EMPLOYEE,
        notice_type=T.NOTICE_ADMIN_CHARGE,
        first_notice_at="2026-08-01T00:00:00.000Z",
        alleged_damages_cents=6000000,
    )
    claim_id = claim["id"]
    assert claim["status"] == T.CLAIM_REPORTED

    # A REPORTED claim admits neither a decision, a close nor a reopen.
    validate_error(
        api.coverage_decision(claim_id, F.coverage_decision(T.DECISION_ACCEPT), U.ADJUSTER),
        E.ERR_COVERAGE_ALREADY_DECIDED,
        409,
    )
    validate_error(api.close_claim(claim_id, U.ADJUSTER), E.ERR_CLAIM_NOT_CLOSABLE, 409)
    validate_error(api.reopen_claim(claim_id, U.CLAIMS_MANAGER), E.ERR_CLAIM_NOT_REOPENABLE, 409)

    get_success_data(api.start_claim_review(claim_id, U.ADJUSTER))
    validate_error(api.start_claim_review(claim_id, U.ADJUSTER), E.ERR_CLAIM_NOT_REVIEWABLE, 409)
    assert get_success_data(api.get_claim(claim_id, U.ADJUSTER))["status"] == T.CLAIM_UNDER_REVIEW

    get_success_data(api.coverage_decision(claim_id, F.coverage_decision(T.DECISION_ACCEPT), U.ADJUSTER))
    resolution = get_success_data(
        api.create_pre_suit_resolution(
            claim_id,
            F.pre_suit_offer(
                settlement_offer_cents=2500000, offer_expires_at="2026-09-01T00:00:00.000Z"
            ),
            U.ADJUSTER,
        ),
        201,
    )
    accepted = get_success_data(api.accept_pre_suit_resolution(resolution["id"], U.ADJUSTER))
    assert_fields(
        accepted, {"status": T.RESOLUTION_ACCEPTED, "incentive_credit_cents": 750000}
    )
    resolved = get_success_data(api.get_claim(claim_id, U.ADJUSTER))
    assert_fields(
        resolved,
        {
            "status": T.CLAIM_RESOLVED,
            "pre_suit_credit_cents": 750000,
            "applied_retention_cents": 1750000,
        },
    )

    validate_error(
        api.accept_pre_suit_resolution(resolution["id"], U.ADJUSTER),
        E.ERR_RESOLUTION_NOT_ACCEPTABLE,
        409,
    )
    assert get_success_data(api.get_claim(claim_id, U.ADJUSTER))["pre_suit_credit_cents"] == 750000

    get_success_data(api.close_claim(claim_id, U.ADJUSTER))
    reopened = get_success_data(api.reopen_claim(claim_id, U.CLAIMS_MANAGER))
    assert_fields(reopened, {"status": T.CLAIM_UNDER_REVIEW, "reopen_count": 1})

    denied = get_success_data(
        api.coverage_decision(
            claim_id,
            F.coverage_decision(T.DECISION_DENY, denial_reason="No covered wrongful act on re-review"),
            U.ADJUSTER,
        )
    )
    assert_fields(
        denied,
        {
            "status": T.CLAIM_COVERAGE_DENIED,
            "denial_reason": "No covered wrongful act on re-review",
        },
    )
    assert get_success_data(api.close_claim(claim_id, U.ADJUSTER))["status"] == T.CLAIM_CLOSED

    validate_error(api.reopen_claim(claim_id, U.CLAIMS_MANAGER), E.ERR_CLAIM_REOPEN_LIMIT, 409)
    assert get_success_data(api.get_claim(claim_id, U.ADJUSTER))["reopen_count"] == 1

    assert get_success_data(api.suspend_panel_firm(firm["id"], U.ADMIN))["status"] == T.PANEL_SUSPENDED
    validate_error(
        api.suspend_panel_firm(firm["id"], U.ADMIN), E.ERR_PANEL_FIRM_NOT_SUSPENDABLE, 409
    )
    assert get_success_data(api.get_panel_firm(firm["id"], U.ADMIN))["status"] == T.PANEL_SUSPENDED

    revoked = get_success_data(
        api.revoke_risk_service(service["id"], "Purchased in error", U.UNDERWRITER)
    )
    assert revoked["status"] == T.SERVICE_REVOKED
    validate_error(
        api.revoke_risk_service(service["id"], "Again", U.UNDERWRITER),
        E.ERR_SERVICE_NOT_REVOCABLE,
        409,
    )
    assert get_success_data(api.get_risk_service(service["id"], U.UNDERWRITER))["status"] == T.SERVICE_REVOKED


def test_defense_and_payment_state_errors_are_all_reachable(api):
    """Six own-state refusals on one invoice, one payment and one matter.

    PRD: "Approval releases the money and is an adjuster action on an invoice in
    `UNDER_AUDIT`; any other status is `ERR_INVOICE_NOT_APPROVABLE`."

    PRD: "Voiding a payment is a `ClaimsManager` action from either
    `PENDING_APPROVAL` or `APPROVED`, and it records a mandatory `void_reason`; a
    payment already `VOIDED` is `ERR_PAYMENT_NOT_VOIDABLE`."

    Design: Corner/errors/defense_and_payment_state_errors_are_all_reachable
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
    policy_id = S.bind_policy(api, assessment["id"])["id"]
    claim = S.accepted_claim(
        api,
        policy_id,
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
    assert invoice["status"] == T.INVOICE_SUBMITTED

    validate_error(
        api.dispute_invoice(
            invoice["id"], F.invoice_dispute(partner_hours=1.0), U.panel_counsel(firm["id"])
        ),
        E.ERR_INVOICE_NOT_DISPUTABLE,
        409,
    )
    # The own-state check at priority 8 outranks the retention gate.
    validate_error(
        api.approve_invoice(invoice["id"], U.ADJUSTER_2), E.ERR_INVOICE_NOT_APPROVABLE, 409
    )

    audited = get_success_data(api.audit_invoice(invoice["id"], U.ADJUSTER))
    assert_fields(
        audited, {"status": T.INVOICE_UNDER_AUDIT, "allowed_amount_cents": 450000}
    )
    validate_error(api.audit_invoice(invoice["id"], U.ADJUSTER), E.ERR_INVOICE_NOT_AUDITABLE, 409)
    assert get_success_data(api.get_invoice(invoice["id"], U.ADJUSTER))["allowed_amount_cents"] == 450000

    payment = S.pending_payment(api, policy_id, claim["id"], 2500000)
    approved = get_success_data(api.approve_payment(payment["id"], U.CLAIMS_MANAGER))
    assert_fields(
        approved,
        {
            "status": T.PAYMENT_APPROVED,
            "retention_portion_cents": 2500000,
            "insurer_portion_cents": 0,
        },
    )
    validate_error(
        api.approve_payment(payment["id"], U.CLAIMS_MANAGER), E.ERR_PAYMENT_NOT_APPROVABLE, 409
    )

    voided = get_success_data(
        api.void_payment(payment["id"], "Settlement collapsed", U.CLAIMS_MANAGER)
    )
    assert voided["status"] == T.PAYMENT_VOIDED
    assert get_success_data(api.get_claim(claim["id"], U.ADJUSTER))["retention_satisfied_cents"] == 0
    validate_error(
        api.void_payment(payment["id"], "Again", U.CLAIMS_MANAGER), E.ERR_PAYMENT_NOT_VOIDABLE, 409
    )

    closed = get_success_data(api.close_assignment(assignment["id"], U.ADJUSTER))
    assert closed["status"] == T.ASSIGNMENT_CLOSED
    validate_error(
        api.close_assignment(assignment["id"], U.ADJUSTER), E.ERR_ASSIGNMENT_NOT_CLOSABLE, 409
    )
    assert get_success_data(api.get_panel_firm(firm["id"], U.ADMIN))["open_matter_count"] == 0


def test_a_missing_or_blank_user_header_is_unauthenticated(api):
    """The very first check: no principal, no request — and no row written.

    PRD: "If `X-User-ID` is absent or empty, the request is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401) before anything else is examined — this is
    the very first check performed on any request."

    Design: Corner/errors/a_missing_or_blank_user_header_is_unauthenticated
    """
    validate_error(
        api.list_jurisdictions(U.missing_user_id()), E.ERR_UNAUTHENTICATED, 401
    )
    validate_error(api.list_jurisdictions(U.blank_user_id()), E.ERR_UNAUTHENTICATED, 401)

    response = api.create_jurisdiction(F.jurisdiction("TX"), U.blank_user_id())
    data = validate_error(response, E.ERR_UNAUTHENTICATED, 401)
    assert data["message"], "the 401 must carry a non-empty message"
    assert_error_meta_only(response.json())

    rows, meta = validate_paginated(api.list_jurisdictions(U.ADMIN))
    assert meta["total_count"] == 0, "the unauthenticated write must not have been applied"
    assert rows == []
