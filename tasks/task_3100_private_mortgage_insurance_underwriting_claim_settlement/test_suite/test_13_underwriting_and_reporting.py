"""The underwriting workbench, application lockdowns and delinquency reporting."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, create_book, setup_loan, submit_application,
    approve_delegated, underwrite_and_approve, file_claim, begin_claim_review,
    add_servicer, make_servicer_headers, set_clock,
    ADMIN, UNDERWRITER, assert_instant_equals,
)


def test_underwrite_moves_the_application_into_non_delegated_underwriting():
    """PRD §3.1: "An `Underwriter` may take it into non-delegated underwriting,
    which moves it to `IN_UNDERWRITING`, stamps `underwritten_utc` from the
    logical clock, and records `underwriting_path` as `NON_DELEGATED`."

    Design: Corner/state_machines/coverage_application_underwrite_moves_the_application_to_in_underwriting
    """
    book = create_book(lender_delegated=False)
    application = submit_application(book, borrower_reference="SM-1")

    response = api_client.underwrite_application(application["id"], UNDERWRITER)
    data = validate_success(response)

    assert data["status"] == "IN_UNDERWRITING"
    assert data["underwriting_path"] == "NON_DELEGATED"
    assert_instant_equals(data["underwritten_utc"],
                          "2026-09-01T00:00:00Z", "underwritten_utc")
    assert data["version"] == application["version"] + 1


def test_delegated_approval_is_refused_for_a_lender_without_delegated_authority():
    """PRD §3.1: "A lender without delegated authority attempting this path is
    refused with the same `ERR_PATH_MISMATCH`."

    Design: Corner/state_machines/delegated_approve_is_refused_for_a_lender_without_delegated_authority
    """
    book = create_book(lender_delegated=False)
    application = submit_application(book, borrower_reference="SM-2")

    response = api_client.delegated_approve_application(
        application["id"], book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_PATH_MISMATCH)

    still = get_success_data(api_client.get_application(application["id"], ADMIN))
    assert still["status"] == "SUBMITTED"
    assert still["approved_coverage_percent"] == 0


def test_delegated_approval_freezes_the_rate_and_computes_the_coverage_base():
    """PRD §3.1: "this records `underwriting_path` as `DELEGATED`, sets
    `approved_coverage_percent` to the requested `coverage_percent` without any
    underwriting step-down, pins `rate_bps_applied` from the card, and computes
    the coverage base."
    PRD §3.2: "It is always an integer number of cents obtained by multiplying
    the note amount by the coverage percentage, dividing by one hundred, and
    discarding any fractional cent".

    Design: Corner/state_machines/delegated_approve_freezes_the_rate_and_computes_the_coverage_base
    """
    book = create_book()
    application = submit_application(book, borrower_reference="SM-3")

    response = api_client.delegated_approve_application(
        application["id"], book["lender_headers"])
    data = validate_success(response)

    assert data["status"] == "APPROVED"
    assert data["underwriting_path"] == "DELEGATED"
    assert data["approved_coverage_percent"] == 25
    assert data["rate_bps_applied"] == 62
    assert data["coverage_base_upb_cents"] == 8_500_000


def test_withdraw_is_refused_once_the_application_is_approved():
    """PRD §3.1: "`APPROVED`, `DECLINED` and `WITHDRAWN` are terminal for the
    application."
    PRD §2.12: "a transition requested from a state that does not declare it
    yields `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/coverage_application_withdraw_is_rejected_after_approval
    """
    book = create_book()
    application = submit_application(book, borrower_reference="SM-5")
    approve_delegated(book, application["id"])

    response = api_client.withdraw_application(application["id"], book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
    assert get_success_data(api_client.get_application(
        application["id"], ADMIN))["status"] == "APPROVED"

    # Every forward transition is closed from the terminal state too.
    response_two = api_client.underwrite_application(application["id"], UNDERWRITER)
    validate_error(response_two, ApiErrorId.ERR_INVALID_STATE_TRANSITION)


def test_begin_review_from_a_denied_claim_is_an_invalid_transition():
    """PRD §3.7: "The same reconsideration operation is available from `DENIED`,
    where it re-opens the denial and returns the claim to `FILED`".
    PRD §2.12: "a transition requested from a state that does not declare it
    yields `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/claim_deny_then_begin_review_is_an_invalid_transition
    """
    book = setup_loan()
    claim = file_claim(book)
    begin_claim_review(claim["id"])
    denied = get_success_data(api_client.deny_claim(
        claim["id"], {"denial_reason": "Insufficient documentation"}, UNDERWRITER))
    assert denied["status"] == "DENIED"

    response = api_client.begin_claim_review(claim["id"], UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    still = get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))
    assert still["status"] == "DENIED"
    assert still["version"] == denied["version"]

    # Reconsideration is the transition DENIED does declare.
    reopened = api_client.reconsider_claim(
        claim["id"], {"reason": "Documentation supplied"}, book["lender_headers"])
    assert validate_success(reopened)["status"] == "FILED"


def test_delinquency_reporting_enforces_the_servicer_guards_and_records_filed():
    """PRD §3.4: "The reporting servicer must be `ACTIVE`; a report from a
    suspended servicer is refused with `ERR_SERVICER_INACTIVE`. The reporting
    servicer must also be the loan's own designated servicer; a report from any
    other organization is refused with `ERR_SERVICER_NOT_DESIGNATED`."
    PRD §3.4: "Reports never change state. Each is created in `FILED` and remains
    there".

    Design: Corner/state_machines/delinquency_report_is_append_only_and_points_back_at_the_loan
    """
    book = setup_loan()
    suspended = add_servicer(servicer_name="Redline Servicing", tier="TIER_3")
    get_success_data(api_client.suspend_servicer(suspended["id"], ADMIN))
    active_other = add_servicer(servicer_name="Basin Servicing", tier="TIER_2")

    base = {
        "loan_id": book["loan_id"],
        "as_of_period": "2026-01",
        "delinquency_class": "A",
        "months_delinquent": 2,
        "loss_mitigation_activities": [],
    }

    inactive = api_client.create_delinquency_report(
        dict(base, servicer_id=suspended["id"]), make_servicer_headers(suspended["id"]))
    validate_error(inactive, ApiErrorId.ERR_SERVICER_INACTIVE)
    assert get_success_data(api_client.list_loan_delinquency_reports(
        book["loan_id"], UNDERWRITER)) == []

    not_designated = api_client.create_delinquency_report(
        dict(base, servicer_id=active_other["id"]), make_servicer_headers(active_other["id"]))
    validate_error(not_designated, ApiErrorId.ERR_SERVICER_NOT_DESIGNATED)

    accepted = api_client.create_delinquency_report(
        dict(base, servicer_id=book["servicer_id"]), book["servicer_headers"])
    report = validate_success(accepted, expected_status=201)
    assert report["status"] == "FILED"
    assert_instant_equals(report["effective_utc"],
                          "2026-01-05T00:00:00Z", "effective_utc")
    assert report["loan_id"] == book["loan_id"]