"""Boundary precision and validation-precedence conflicts."""
import pytest

from prd_bench_local_runner.testing import validate_success, validate_error, get_success_data

from test_helpers import (
    ApiErrorId, api_client, setup_loan, setup_two_loans, create_book,
    submit_application, approve_delegated, issue_loan, file_claim, refresh_loan,
    reconcile_exposure, setup_dispute, file_delinquency_report,
    file_servicer_cancellation, set_clock, make_servicer_headers,
    ADMIN, UNDERWRITER, assert_instant_equals, amortize_into_at80,
    AT80_MAX_REFUND_CENTS,
)


class TestLenderExposureBoundary:

    def test_exposure_contribution_equal_to_the_cap_reconciles_successfully(self):
        """PRD §3.12: "The canonical illustration: a policy carrying a
        contribution rate of 0.35 makes an 8500000-cent coverage base contribute
        2975000 cents".
        PRD §3.12: "Reconciliation is refused with `ERR_LENDER_EXPOSURE_CAP_EXCEEDED`
        when the contribution strictly exceeds the cap — strictly, so a
        contribution exactly equal to the cap is permitted".

        Design: Difficulty/boundary_precision_check/lender_exposure_cap_is_strictly_exceeded_not_merely_reached
        """
        book = setup_loan(lender_cap=2_975_000)
        response = reconcile_exposure(book)
        data = validate_success(response)

        assert data["lender_id"] == book["lender_id"]
        assert data["lender_contribution_cents"] == 2_975_000
        assert abs(data["used_pct"] - 100.0) < 0.0001
        assert data["warn"] is True

    def test_exposure_contribution_one_cent_over_the_cap_is_refused_and_suspends_the_lender(self):
        """PRD §3.12: "a contribution one cent over is not — and a refused
        reconciliation additionally drives the lender's status to `SUSPENDED` as
        it returns that error against the lender."

        Design: Difficulty/boundary_precision_check/lender_exposure_cap_is_strictly_exceeded_not_merely_reached
        """
        book = setup_loan(lender_cap=2_974_999)
        response = reconcile_exposure(book)
        validate_error(response, ApiErrorId.ERR_LENDER_EXPOSURE_CAP_EXCEEDED)

        lender = get_success_data(api_client.get_lender(book["lender_id"], UNDERWRITER))
        assert lender["status"] == "SUSPENDED"


def test_empty_in_force_book_yields_null_concentration_without_error():
    """PRD §3.12: "An empty book is a valid snapshot: it yields a null
    concentration index and no segments."
    PRD §3.12: "reported as null when the in-force book is empty".

    Design: Difficulty/boundary_precision_check/empty_in_force_book_yields_null_concentration_without_error
    """
    # An empty in-force book: the policy and parties exist, no loan does.
    create_book()
    response = api_client.create_snapshot({
        "snapshot_utc": "2026-09-01T00:00:00Z",
        "cluster_in_force_threshold_cents": 17_000_000,
    }, ADMIN)
    data = validate_success(response, expected_status=201)

    assert data["lender_concentration_index"] is None
    assert data["geography_totals"] == []
    assert data["segment_statuses"] == []
    assert data["aggregate_ceded_cents"] == 0
    assert data["status"] == "COMPUTED"


def test_state_check_wins_over_the_open_dispute_rule_on_a_filed_claim():
    """PRD §2.12: "Fourth comes the state check: a transition requested from a
    state that does not declare it yields `ERR_INVALID_STATE_TRANSITION`."
    PRD §3.11: "Settlement is admissible from `APPROVED` and from nowhere else."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_claim_settlement
    """
    book = setup_loan()
    claim = file_claim(book)
    # A non-LOSS_MITIGATION_EXCUSE dispute is open against the still-FILED claim.
    setup_dispute(book, grounds="ORIGINATION_OMISSION", claim_id=claim["id"])

    loan = refresh_loan(book)
    response = api_client.settle_claim(claim["id"], {
        "settlement_option_kind": "CASH",
        "expected_claim_version": claim["version"],
        "expected_loan_version": loan["version"],
    }, book["lender_headers"])
    validate_error(response, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

    assert get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))["status"] == "FILED"


def test_loss_mitigation_gate_wins_over_the_coverage_temporal_check():
    """PRD §2.12: "The rescission-relief bar (`ERR_RESCISSION_BARRED_RELIEF_ATTACHED`)
    is evaluated before the claim filing bar (`ERR_CLAIM_TIME_BARRED`), which in
    turn precedes the loss-mitigation gate (`ERR_CLAIM_BLOCKED_LOSS_MITIGATION`)."
    PRD §3.8: "Coverage must have been in force at the claim's event instant,
    meaning the loan's coverage axis was `ACTIVE` then; otherwise the approval is
    refused with `ERR_COVERAGE_NOT_ACTIVE`. The loan's `claim_blocked` flag must
    be false at the same instant; otherwise the refusal is
    `ERR_CLAIM_BLOCKED_LOSS_MITIGATION`."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_temporal_on_claim_approval
    """
    book = setup_loan()
    # Amortize into the AT_80 window first, so the cancellation carries a non-zero
    # maximum refund: PRD §3.6 refuses a cancellation "Where the computed maximum
    # refund is zero ... a factor of zero is not a cancellation ground", and this
    # scenario needs an admissible cancellation rather than a refund argument.
    amortize_into_at80(book)
    # A single Class-A report meeting only outreach fails the standard.
    file_delinquency_report(
        book, as_of_period="2026-01", months_delinquent=2,
        loss_mitigation_activities=[
            {"activity_kind": "OUTREACH_SENT", "outcome": "COMPLETED",
             "activity_utc": "2026-01-10T00:00:00Z"}])
    assert refresh_loan(book)["claim_blocked"] is True

    file_servicer_cancellation(book, notice_utc="2026-01-20T00:00:00Z",
                               applied_utc="2026-02-20T00:00:00Z",
                               evidence_cents=AT80_MAX_REFUND_CENTS)
    set_clock("2026-03-25T00:00:00Z")
    loan = refresh_loan(book)
    assert loan["coverage_status"] == "CANCELLED"
    assert_instant_equals(loan["cancellation_effective_utc"],
                          "2026-02-20T00:00:00Z", "cancellation_effective_utc")

    # The claim's event instant falls after the cancellation took effect, so both
    # the temporal check and the loss-mitigation gate are violated.
    claim = file_claim(book, event_completed_utc="2026-03-01T00:00:00Z")
    get_success_data(api_client.begin_claim_review(claim["id"], UNDERWRITER))

    response = api_client.approve_claim(claim["id"], UNDERWRITER)
    validate_error(response, ApiErrorId.ERR_CLAIM_BLOCKED_LOSS_MITIGATION)
    assert get_success_data(api_client.get_claim(claim["id"], UNDERWRITER))["status"] == "UNDER_REVIEW"