"""Corner queue: rbac — role exclusivity on decisions, segregation of duties
between verifiers, and the Anonymous role's single capability."""
from test_helpers import (
    EXPECTED_SUCCESS_STATUS,
    TEST_USERS,
    ApiErrorId,
    application_decision_payload,
    create_application_payload,
    milestone_decision_payload,
    milestone_payload,
    new_context,
    setup_active_loan,
    setup_application_in_decision_pending,
    setup_declaration,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_loan_officer_cannot_decide_application(api):
    """PRD §3.6: "A `LoanApprover` renders the decision on an application in `DECISION_PENDING` — any other status is rejected with `ERR_APPLICATION_NOT_DECISION_PENDING`."
    PRD §2.1: "A request whose role is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/loan_officer_cannot_decide_application
    """
    ctx = setup_application_in_decision_pending(
        requested_amount_cents=2500000,
        assessed_loss_cents=2500000,
        insurance_proceeds_cents=0)
    app_id = ctx["application"]["id"]

    # The LoanOfficer may file credit reviews but may not render the decision.
    resp = api.decide_application(
        app_id, application_decision_payload(decision="APPROVED"),
        ctx["officer_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    application = validate_success(
        api.get_application(app_id, ctx["officer_headers"]),
        EXPECTED_SUCCESS_STATUS["get_application"])
    assert application["status"] == "DECISION_PENDING"
    assert application["loan_id"] is None


def test_segregation_of_duties_blocks_same_verifier_on_milestones(api):
    """PRD §2.1: "Segregation of duties is enforced between two staff roles: the `LossVerifier` who decides a repair milestone must not be the same user who completed the application's latest completed damage verification, and a violation is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
    PRD §3.7: "A decision of `VERIFIED` records a `verified_cost_cents` between zero and `claimed_cost_cents` inclusive — anything outside that band is `ERR_INVALID_REQUEST` — stamps the milestone's `verifier_user_id`, and re-runs the tranche eligibility walk, flipping any tranche that has crossed its threshold from `SCHEDULED` to `ELIGIBLE`."

    Design: Corner/rbac/segregation_of_duties_blocks_same_verifier_on_milestones
    """
    # ctx["verifier_headers"] completed the application's damage verification;
    # ctx["milestone_verifier_headers"] is a different LossVerifier user.
    ctx = setup_active_loan()
    loan_id = ctx["loan"]["id"]

    resp = api.create_milestone(
        loan_id,
        milestone_payload(description="roof", claimed_cost_cents=2500000),
        ctx["applicant_headers"])
    milestone = validate_success(resp, EXPECTED_SUCCESS_STATUS["create_milestone"])
    assert milestone["status"] == "REPORTED"

    # The damage verifier of record is refused.
    resp = api.decide_milestone(
        milestone["id"],
        milestone_decision_payload(decision="VERIFIED",
                                   verified_cost_cents=2500000),
        ctx["verifier_headers"])
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    rows = validate_success(
        api.list_milestones(loan_id, ctx["servicing_headers"]),
        EXPECTED_SUCCESS_STATUS["list_milestones"])
    assert rows[0]["status"] == "REPORTED"

    # A different LossVerifier on the same loan succeeds.
    resp = api.decide_milestone(
        milestone["id"],
        milestone_decision_payload(decision="VERIFIED",
                                   verified_cost_cents=2500000),
        ctx["milestone_verifier_headers"])
    decided = validate_success(resp, EXPECTED_SUCCESS_STATUS["decide_milestone"])
    assert decided["status"] == "VERIFIED"
    assert decided["verifier_user_id"] == (
        ctx["milestone_verifier_headers"]["X-User-ID"])


def test_anonymous_cannot_create_application(api):
    """PRD §2.1: "`Anonymous` — an unauthenticated registrant who may only self-register as an applicant."
    PRD §2.1: "A request whose role is not in the endpoint's authorized role list is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    Design: Corner/rbac/anonymous_cannot_create_application
    """
    ctx = new_context()
    setup_declaration(ctx)

    resp = api.create_application(
        create_application_payload(
            ctx["declaration"]["id"], requested_amount_cents=2500000),
        TEST_USERS["anonymous_headers"])
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    rows, _meta = validate_paginated(
        api.list_applications(ctx["officer_headers"]))
    assert rows == []
