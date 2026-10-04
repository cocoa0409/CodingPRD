"""Role-based access control: authentication, exclusive operations and the
peer-role model."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan, setup_loan_with_filed_claim, file_claim,
    create_book, submit_application, underwrite_and_approve, refresh_loan,
    setup_approved_claim_for_loan, create_claim_payload, setup_dispute,
    ADMIN, UNDERWRITER, BORROWER,
)


def test_missing_identity_headers_are_rejected_before_any_lookup():
    """PRD §2.1: "A request that omits either header, or presents a malformed
    value, is refused with `ERR_UNAUTHENTICATED` (HTTP 401)."
    PRD §2.12: "Authentication is checked first: absent or malformed identity
    headers yield `ERR_UNAUTHENTICATED` before anything else is examined."

    Design: Corner/validations/missing_user_context_headers_are_rejected_before_any_lookup
    """
    book = setup_loan()

    # The loan exists, yet the absent header is reported ahead of any lookup.
    response = api_client.get_loan(book["loan_id"], {})
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED)


def test_borrower_is_denied_the_exclusive_lender_operation_of_filing_a_claim():
    """PRD §2.1: "Even with valid headers, an operation is only admissible to the
    roles enumerated for it; a caller whose role is well-formed but not permitted
    for the operation is refused with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."
    PRD §4: the `POST /mortgage-insurance/claims` row lists `Lender` as its
    authorized role.

    Design: Corner/validations/borrower_role_is_denied_the_exclusive_lender_operation_of_filing_a_claim
    """
    book = setup_loan()
    payload = create_claim_payload()
    payload["loan_id"] = book["loan_id"]

    response = api_client.create_claim(payload, BORROWER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api_client.list_loan_claims(
        book["loan_id"], UNDERWRITER)) == []

    # The same call from the owning lender succeeds.
    accepted = api_client.create_claim(payload, book["lender_headers"])
    validate_success(accepted, expected_status=201)


def test_borrower_is_barred_from_submitting_a_coverage_application():
    """PRD §2.1: "Note in particular that a borrower is barred from submitting a
    coverage application: the submission operation is restricted to the `Lender`
    role."
    PRD §3.1: "Because the borrower cannot act on its own behalf here, a
    submission attempted under the `Borrower` role is refused outright."

    Design: Corner/validations/borrower_role_is_denied_the_exclusive_lender_operation_of_filing_a_claim
    """
    book = create_book()
    payload = {
        "lender_id": book["lender_id"],
        "master_policy_id": book["mp_id"],
        "rate_card_id": book["rate_card_id"],
        "borrower_reference": "RBAC-APP",
        "loan_amount_cents": 34_000_000,
        "property_value_cents": 40_000_000,
        "credit_grade": "B",
        "coverage_percent": 25,
        "premium_plan": "BPM",
        "borrower_paid": True,
        "financed_premium": False,
        "county_code": "06037",
        "term_months": 360,
    }
    response = api_client.create_application(payload, BORROWER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)


def test_underwriting_approval_is_denied_to_the_lender_that_owns_the_application():
    """PRD §2.1: "`Underwriter` owns the non-delegated underwriting queue (taking
    an application into underwriting, requesting information, approving and
    declining)".
    PRD §3.1: "An `Underwriter` approving an application out of `IN_UNDERWRITING`
    begins from the lender's requested `coverage_percent`".

    Design: Corner/validations/underwriting_transitions_are_denied_to_the_lender_that_owns_the_application
    """
    book = create_book(lender_delegated=False)
    application = submit_application(book, borrower_reference="RBAC-2")
    get_success_data(api_client.underwrite_application(application["id"], UNDERWRITER))

    response = api_client.approve_application(application["id"], book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api_client.get_application(
        application["id"], ADMIN))["status"] == "IN_UNDERWRITING"

    # The underwriter, not the owning lender, holds the operation.
    accepted = api_client.approve_application(application["id"], UNDERWRITER)
    assert validate_success(accepted)["status"] == "APPROVED"


def test_servicer_cannot_decide_a_coverage_dispute_even_when_named_on_the_loan():
    """PRD §2.1: "Configuration and issuance belong to `MasterPolicyAdmin` alone:
    master policies, rate cards, reinsurance treaties and their cancellation,
    servicers and their suspension, lenders, loan issuance, the rescission-relief
    record, dispute review and decision, portfolio snapshots, and the logical
    clock are all `MasterPolicyAdmin` operations."

    Design: Corner/rbac/servicer_cannot_decide_a_coverage_dispute_even_when_named_on_the_loan
    """
    book = setup_loan()
    setup_approved_claim_for_loan(book)
    dispute = setup_dispute(book, grounds="VALUATION_ERROR", in_review=True)

    response = api_client.decide_dispute(dispute["id"], {
        "decision": "UPHELD",
        "decision_reason": "Validated value supports the origination figure",
    }, book["servicer_headers"])
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
    assert get_success_data(api_client.get_dispute(
        dispute["id"], ADMIN))["status"] == "UNDER_REVIEW"

    accepted = api_client.decide_dispute(dispute["id"], {
        "decision": "UPHELD",
        "decision_reason": "Validated value supports the origination figure",
    }, ADMIN)
    assert validate_success(accepted)["decision"] == "UPHELD"


def test_underwriter_cannot_create_a_rate_card_but_may_publish_a_snapshot():
    """PRD §2.1: "Exposure reconciliation, manual reinsurance cessions and
    portfolio snapshots are shared between `MasterPolicyAdmin` and `Underwriter`."
    PRD §2.1: "Configuration and issuance belong to `MasterPolicyAdmin` alone:
    master policies, rate cards, reinsurance treaties and their cancellation".

    Design: Corner/rbac/underwriter_can_read_the_portfolio_snapshot_but_cannot_publish_a_policy_rate_card
    """
    book = create_book()
    response = api_client.create_rate_card({
        "master_policy_id": book["mp_id"],
        "credit_grade": "C",
        "ltv_band": "851_TO_90",
        "coverage_percent": 30,
        "premium_plan": "BPM",
        "rate_bps": 95,
        "min_borrower_reserves_months": 2,
    }, UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)

    assert get_success_data(api_client.list_rate_cards(
        ADMIN, params={"master_policy_id": book["mp_id"]})) \
        == [book["rate_card"]]

    # The same creation belongs to the admin role alone.
    accepted = api_client.create_rate_card({
        "master_policy_id": book["mp_id"],
        "credit_grade": "C",
        "ltv_band": "851_TO_90",
        "coverage_percent": 30,
        "premium_plan": "BPM",
        "rate_bps": 95,
        "min_borrower_reserves_months": 2,
    }, ADMIN)
    validate_success(accepted, expected_status=201)

    # Snapshot publication is genuinely shared with the underwriter.
    snapshot = api_client.create_snapshot({
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 17_000_000,
    }, UNDERWRITER)
    validate_success(snapshot, expected_status=201)