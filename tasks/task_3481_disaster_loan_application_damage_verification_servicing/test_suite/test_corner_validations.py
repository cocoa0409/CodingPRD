"""Corner queue: validations — authentication, role authorization, ownership,
conditional shape gates, and cross-field request rules."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    ApiErrorId,
    create_application_payload,
    create_verification_payload,
    credit_review_payload,
    grant_award_payload,
    register_applicant,
    setup_application_in_decision_pending,
    setup_application_in_verification,
    setup_draft_application,
    setup_submitted_application,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_submit_missing_headers_unauthenticated(api):
    """PRD §2.1: "Every request carries two headers: `X-User-ID`, identifying the acting user, and `X-User-Role`, naming the role under which that user acts. A request missing either header, or carrying an empty value for either, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/validations/submit_missing_headers_unauthenticated
    """
    ctx = setup_draft_application(requested_amount_cents=2500000)
    app_id = ctx["application"]["id"]

    # No X-User-Role / X-User-ID headers at all.
    resp = api.submit_application(app_id, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DRAFT"


def test_wrong_role_credit_review_unauthorized(api):
    """PRD §2.1: "A request whose role is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §3.3: "Once an application is `SUBMITTED`, a `LoanOfficer` files a credit review against it; filing against an application in any other status is rejected with `ERR_APPLICATION_NOT_SUBMITTED`."

    Design: Corner/validations/wrong_role_credit_review_unauthorized
    """
    ctx = setup_submitted_application(requested_amount_cents=2500000)
    app_id = ctx["application"]["id"]

    # The Applicant role — even the owner — may not file a credit review.
    resp = api.create_credit_review(
        app_id,
        credit_review_payload(credit_score=700,
                              verified_monthly_debt_cents=100000),
        ctx["applicant_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    rows = validate_success(
        api.list_credit_reviews(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["list_credit_reviews"])
    assert rows == []
    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "SUBMITTED"


def test_cross_owner_submit_forbidden(api):
    """PRD §2.1: "When `X-User-Role` is `Applicant`, `X-User-ID` is the `id` of the acting `Applicant` record; ownership checks on any resource that references an applicant — an application, a loan, a verification reached through its application, a milestone or servicing action or settlement reached through its loan, a receivable reached through its loan — compare the resource's `applicant_id` to `X-User-ID`, and a mismatch is rejected with `ERR_FORBIDDEN_OWNER` (HTTP 403)."
    PRD §3.2: "The caller must own the application, else `ERR_FORBIDDEN_OWNER`."

    Design: Corner/validations/cross_owner_submit_forbidden
    """
    ctx = setup_draft_application(requested_amount_cents=2500000)
    owner = ctx["applicant"]
    intruder, intruder_headers = register_applicant()
    app_id = ctx["application"]["id"]

    # Applicant B's X-User-ID does not match the application's applicant_id.
    resp = api.submit_application(app_id, intruder_headers)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN_OWNER)

    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DRAFT"
    assert application["applicant_id"] == owner["id"]


def test_estimation_method_boundary_2500000(api):
    """PRD §3.4: "The verifier chooses a `method` of `INSPECTION` or `ESTIMATION`; the estimation shortcut is reserved for smaller asks, so `ESTIMATION` is allowed only when the application's `requested_amount_cents` is at most 2500000 cents ($25,000), and a larger request is rejected with `ERR_ESTIMATION_NOT_ALLOWED` (HTTP 422)."

    Design: Corner/validations/estimation_method_boundary_2500000
    """
    ctx = setup_application_in_verification(requested_amount_cents=2500000)
    app1_id = ctx["application"]["id"]
    ctx = setup_application_in_verification(
        _ctx=ctx, requested_amount_cents=2500001)
    app2_id = ctx["application"]["id"]

    # 2500000 is exactly the inclusive ceiling: ESTIMATION is allowed.
    resp = api.create_damage_verification(
        app1_id,
        create_verification_payload(method="ESTIMATION"),
        ctx["verifier_headers"])
    verification = validate_success(
        resp, EXPECTED_SUCCESS_STATUS["create_damage_verification"])
    assert verification["status"] == "REQUESTED"

    # One cent over: rejected; the application stays in VERIFICATION.
    resp = api.create_damage_verification(
        app2_id,
        create_verification_payload(method="ESTIMATION"),
        ctx["verifier_headers"])
    validate_error(resp, ApiErrorId.ERR_ESTIMATION_NOT_ALLOWED)
    application = validate_success(
        api.get_application(app2_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "VERIFICATION"

    # The same application can still proceed via INSPECTION.
    resp = api.create_damage_verification(
        app2_id,
        create_verification_payload(method="INSPECTION"),
        ctx["verifier_headers"])
    validate_success(resp, EXPECTED_SUCCESS_STATUS["create_damage_verification"])


def test_grant_wrong_purpose_category_rejected(api):
    """PRD §3.5: "The report names the `program_name`, an `award_amount_cents` strictly greater than zero, and a `purpose_category` of `PHYSICAL_DAMAGE` or `ECONOMIC_INJURY` that must equal the application's `loan_purpose` — a mismatched category is rejected with `ERR_INVALID_REQUEST`."

    Design: Corner/validations/grant_wrong_purpose_category_rejected
    """
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=9000000,
        assessed_loss_cents=9000000,
        insurance_proceeds_cents=0)

    # PHYSICAL_DAMAGE application; ECONOMIC_INJURY grant category mismatches.
    resp = api.create_grant_award(
        ctx["application"]["id"],
        grant_award_payload(program_name="EIDL-ADV",
                            award_amount_cents=100000,
                            purpose_category="ECONOMIC_INJURY"),
        ctx["grant_coordinator_headers"])
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    rows = validate_success(
        api.list_grant_awards(ctx["application"]["id"],
                              ctx["grant_coordinator_headers"]),
        EXPECTED_SUCCESS_STATUS["list_grant_awards"])
    assert rows == []
